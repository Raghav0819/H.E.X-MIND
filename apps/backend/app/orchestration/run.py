"""Run orchestration on Google ADK: SequentialAgent[prepare -> plan -> execute -> finalize].

- prepare:  snapshot the user's workspace, create an isolated git worktree, start the MCP
            workspace server bound to it.
- plan:     the CrewAI Planner crew (called over A2A) breaks the request into Blackboard
            tasks (medium/high complexity); low complexity gets a single task.
- execute:  a pool of workers claims tasks atomically. Each claimed task runs a reflection
            loop, an ADK LoopAgent[coder -> review_gate -> decide]: the CrewAI Coder crew
            (over A2A) edits, the sandbox check runs, the ADK Reviewer (Pydantic ReviewResult)
            judges, and `decide` applies the acceptance rules and escalates to end the loop.
- finalize: diff the worktree against the snapshot, record file_changes, emit diff_ready, and
            wait for the user's approval. Nothing touches the user's files here.

Agent claims are not trusted for measurable facts: changed files come from git and check
results from the sandbox.
"""

import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.concurrency import run_in_threadpool
from google.adk.agents import BaseAgent, LlmAgent, LoopAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from pydantic import PrivateAttr
from sqlalchemy import select

from app.a2a.client import call_crew
from app.a2a.protocol import CrewRequest, CrewRole
from app.agents import roles
from app.agents.adk_llm import HexAdkLlm
from app.agents.mcp_bridge import McpWorkspace
from app.blackboard import store
from app.context.workspace_scan import list_files, mentioned_files
from app.db.models import CheckResult, FileChange, Message, Project, Review, Run, Task
from app.events.log import EventType, append_event
from app.memory.store import safely
from app.orchestration.adk import (
    escalate_event,
    model_error_fallback,
    run_adk,
    schema_guard,
    state_event,
)
from app.orchestration.services import Services
from app.providers.router import CallContext
from app.sandbox.runner import CheckOutcome
from app.telemetry.hub import TelemetryHub
from app.workspace import git
from app.workspace.files import content_hash

logger = logging.getLogger(__name__)

MAX_DIFF_FOR_REVIEW = 12_000
_standards_seeded = False


class RunAborted(RuntimeError):
    """A run cannot proceed for a reason the user can fix (shown in run_failed)."""


async def set_status(
    services: Services, run_id: uuid.UUID, status: str, *, finished: bool = False
) -> None:
    async with services.sessionmaker.begin() as session:
        run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        assert run is not None
        previous = run.status
        run.status = status
        now = datetime.now(UTC)
        if run.started_at is None:
            run.started_at = now
        if finished:
            run.finished_at = now
        await append_event(
            session,
            run_id,
            EventType.RUN_STATUS_CHANGED,
            payload={"status": status, "previous": previous, "stub": False},
        )


@dataclass
class RunWorkflow:
    services: Services
    run_id: uuid.UUID
    requires_review: bool = True
    loop: asyncio.AbstractEventLoop = field(default_factory=asyncio.get_running_loop)
    workspace_root: Path | None = None
    worktree: Path | None = None
    base: str | None = None
    request: str = ""
    complexity: str | None = None
    mcp: McpWorkspace | None = None
    telemetry: TelemetryHub = field(init=False)

    def __post_init__(self) -> None:
        self.telemetry = TelemetryHub(self.services, self.run_id, self.loop)

    # ---------- helpers ----------

    async def emit(
        self,
        type: EventType,
        *,
        task_id: uuid.UUID | None = None,
        agent_id: str | None = None,
        **payload: Any,
    ) -> None:
        async with self.services.sessionmaker.begin() as session:
            await append_event(
                session, self.run_id, type, task_id=task_id, agent_id=agent_id, payload=payload
            )

    async def _crew(
        self,
        role: CrewRole,
        prompt: str,
        expected_output: str,
        *,
        agent_id: str,
        parent: str,
        task_id: uuid.UUID | None = None,
    ) -> str:
        """Run a CrewAI crew over A2A (ADK RemoteA2aAgent -> crew service)."""
        assert self.worktree is not None and self.workspace_root is not None
        assert self.services.a2a_http is not None, "no A2A client configured"
        return await call_crew(
            role,
            hub=self.telemetry,
            http=self.services.a2a_http,
            settings=self.services.settings,
            prompt=prompt,
            parent=parent,
            request=CrewRequest(
                exchange_id=uuid.uuid4(),
                run_id=self.run_id,
                task_id=task_id,
                agent_id=agent_id,
                worktree=str(self.worktree),
                workspace=str(self.workspace_root),
                complexity=self.complexity,
                expected_output=expected_output,
            ),
        )

    async def _memory(self, method: str, *args: Any, **kwargs: Any) -> Any:
        memory = self.services.memory
        if memory is None:
            return []
        return await run_in_threadpool(safely, getattr(memory, method), *args, **kwargs)

    # ---------- nodes ----------

    async def prepare(self) -> None:
        global _standards_seeded
        async with self.services.sessionmaker() as session:
            run = await session.get(Run, self.run_id)
            assert run is not None
            project = await session.get(Project, run.project_id)
            assert project is not None
            message = (
                await session.get(Message, run.triggering_message_id)
                if run.triggering_message_id
                else None
            )
        self.request = message.content if message else run.title
        self.complexity = run.complexity
        self.workspace_root = Path(project.workspace_path)

        if not await run_in_threadpool(git.is_repo, self.workspace_root):
            raise RunAborted(
                "The workspace is not a Git repository. Initialize Git for this project so "
                "agent changes can be isolated, reviewed and reverted."
            )
        self.base = await run_in_threadpool(git.snapshot, self.workspace_root)
        self.worktree = self.services.settings.data_dir / "worktrees" / str(self.run_id)
        await run_in_threadpool(
            git.create_worktree,
            self.workspace_root,
            self.base,
            self.worktree,
            f"hexmind/run-{self.run_id.hex[:8]}",
        )
        async with self.services.sessionmaker.begin() as session:
            run = await session.get(Run, self.run_id)
            assert run is not None
            run.base_commit = self.base
            run.worktree_path = str(self.worktree)

        settings = self.services.settings
        self.mcp = McpWorkspace(
            root=self.worktree,
            workspace=self.workspace_root,
            allowed_images=settings.sandbox_images,
            check_timeout_s=settings.sandbox_timeout_s,
        )
        await run_in_threadpool(self.mcp.start)

        if not _standards_seeded and self.services.memory is not None:
            await self._memory("seed_standards", settings.standards_dir)
            _standards_seeded = True
        return

    async def plan(self) -> None:
        await set_status(self.services, self.run_id, "planning")
        standards = await self._memory("standards_for", self.request, k=3)
        prompt = roles.planner_prompt(self.request, standards)
        plan: roles.Plan | None = None
        errors: list[str] = []
        for _ in range(2):  # one repair attempt
            raw = await self._crew(
                "planner",
                prompt,
                "A JSON object with a tasks array",
                agent_id="planner",
                parent="plan",
            )
            try:
                plan = roles.parse_json_output(raw, roles.Plan)
                break
            except roles.OutputError as exc:
                errors.append(str(exc))
                prompt += (
                    f"\n\nYour previous answer was invalid ({exc}). Answer with valid JSON only."
                )
        await self.telemetry.record(
            EventType.SCHEMA_VALIDATED,
            agent_id="planner",
            agent="planner",
            schema_name="Plan",
            status="fallback" if plan is None else "repaired" if errors else "valid",
            errors=[e[:300] for e in errors],
        )
        if plan is None:
            await self._single_task(note="The Planner's output was invalid; using a single task.")
            return

        ids: list[uuid.UUID] = []
        async with self.services.sessionmaker.begin() as session:
            for index, planned in enumerate(plan.tasks):
                depends = [ids[i] for i in planned.depends_on if 0 <= i < len(ids) and i < index]
                try:
                    task = await store.add_task(
                        session,
                        self.run_id,
                        title=planned.title,
                        description=planned.description,
                        acceptance_criteria=planned.acceptance_criteria,
                        target_files=planned.target_files,
                        depends_on=depends,
                        complexity=planned.complexity,
                        max_attempts=self.services.settings.review_max_rounds + 1,
                    )
                except store.DuplicateTask:
                    continue
                ids.append(task.id)
        return

    async def single_task(self) -> None:
        await self._single_task()

    async def _single_task(self, note: str | None = None) -> None:
        assert self.worktree is not None
        files = await run_in_threadpool(list_files, self.worktree)
        description = self.request + (f"\n\n({note})" if note else "")
        async with self.services.sessionmaker.begin() as session:
            run = await session.get(Run, self.run_id)
            assert run is not None
            await store.add_task(
                session,
                self.run_id,
                title=run.title,
                description=description,
                acceptance_criteria=[
                    "The requested change is implemented",
                    "The `test` check passes",
                ],
                target_files=mentioned_files(self.request, files),
                complexity=run.complexity,
                max_attempts=self.services.settings.review_max_rounds + 1,
            )

    async def execute(self) -> None:
        await set_status(self.services, self.run_id, "executing")
        concurrency = max(1, self.services.settings.worker_concurrency)
        await asyncio.gather(*(self._worker(f"coder_{i + 1:02d}") for i in range(concurrency)))
        return

    async def _worker(self, name: str) -> None:
        lease = timedelta(seconds=self.services.settings.task_lease_s)
        while True:
            async with self.services.sessionmaker.begin() as session:
                await store.reap_expired_leases(session, self.run_id)
                task = await store.claim_next(session, self.run_id, name, lease=lease)
            if task is None:
                async with self.services.sessionmaker() as session:
                    if not await store.run_has_open_tasks(session, self.run_id):
                        return
                await asyncio.sleep(0.5)  # another worker holds a dependency or shared file
                continue

            # Model calls can outlast a lease (minutes on a local model), so renew it while
            # working; if it is lost anyway, stop rather than race the new owner.
            work = asyncio.create_task(self._work_on(task, name))
            heartbeat = asyncio.create_task(self._heartbeat(task.id, name, lease, work))
            try:
                await work
            except asyncio.CancelledError:
                if not heartbeat.done() or not heartbeat.result():
                    raise  # the run itself is being cancelled
                logger.warning("worker %s lost its lease on task %s; stopping", name, task.id)
                await self.telemetry.abort_open(task_id=task.id, error="lease lost")
            except Exception as exc:
                logger.exception("task %s failed", task.id)
                await self.telemetry.abort_open(task_id=task.id, error=str(exc))
                await self._finish_task(task.id, "failed", error=str(exc))
            finally:
                heartbeat.cancel()

    async def _heartbeat(
        self, task_id: uuid.UUID, worker: str, lease: timedelta, work: asyncio.Task
    ) -> bool:
        """Renew the lease every quarter lease. Returns True (after cancelling `work`) if the
        lease was lost."""
        while not work.done():
            await asyncio.sleep(lease.total_seconds() / 4)
            async with self.services.sessionmaker.begin() as session:
                renewed = await store.renew_lease(session, task_id, worker, lease=lease)
            if not renewed and not work.done():
                work.cancel()
                return True
        return False

    async def _work_on(self, task: Task, worker: str) -> None:
        async with self.services.sessionmaker.begin() as session:
            await store.transition(session, task.id, "running")
        await self.emit(EventType.TASK_STARTED, task_id=task.id, agent_id=worker, worker=worker)

        query = f"{task.title}\n{task.description}"
        loop_state = TaskLoopState(
            task=task,
            worker=worker,
            rounds=self.services.settings.review_max_rounds + 1,
            standards=await self._memory("standards_for", query, k=3),
            lessons=await self._memory("self_logs_for", query, k=2, exclude_run=str(self.run_id)),
        )
        await run_adk(
            self.telemetry.instrument(
                reflection_loop(self, loop_state), task_id=task.id, parent="execute"
            ),
            message=f"Implement task: {task.title}",
        )
        if not loop_state.finished:  # defensive: the loop must always end with a decision
            await self._finish_task(
                task.id, "failed", error="reflection loop ended without a decision"
            )

    async def _worktree_fingerprint(self) -> frozenset[tuple[str, str]]:
        assert self.worktree is not None and self.base is not None
        changes = await run_in_threadpool(git.diff, self.worktree, self.base)
        return frozenset((c.path, c.diff) for c in changes)

    async def _run_check(self, task_id: uuid.UUID, name: str = "test") -> CheckOutcome:
        assert self.mcp is not None
        await self.emit(EventType.CHECK_STARTED, task_id=task_id, agent_id="sandbox", name=name)
        ok, text = await run_in_threadpool(self.mcp.call_tool, "run_check", {"name": name})
        if ok:
            outcome = CheckOutcome(**json.loads(text))
        else:
            outcome = CheckOutcome(name, None, 0, "", error=text.removeprefix("ERROR: "))
        async with self.services.sessionmaker.begin() as session:
            session.add(
                CheckResult(
                    run_id=self.run_id,
                    task_id=task_id,
                    name=name,
                    exit_code=outcome.exit_code,
                    duration_ms=outcome.duration_ms,
                    output_tail=(outcome.error or "") + outcome.output_tail,
                )
            )
            await append_event(
                session,
                self.run_id,
                EventType.CHECK_COMPLETED,
                task_id=task_id,
                agent_id="sandbox",
                payload={
                    "name": name,
                    "exit_code": outcome.exit_code,
                    "duration_ms": outcome.duration_ms,
                },
            )
        return outcome

    async def _review_prompt(self, task: Task, check: CheckOutcome) -> str:
        assert self.worktree is not None and self.base is not None
        changes = await run_in_threadpool(git.diff, self.worktree, self.base)
        relevant = [c for c in changes if not task.target_files or c.path in task.target_files]
        diff_text = "\n".join(c.diff for c in (relevant or changes))[:MAX_DIFF_FOR_REVIEW]
        standards = await self._memory("standards_for", task.title, k=2)
        return roles.reviewer_prompt(
            title=task.title,
            criteria=task.acceptance_criteria,
            diff=diff_text or "(no changes)",
            check_summary=_check_summary(check),
            standards=standards,
        )

    async def _record_review(self, task: Task, review: roles.ReviewResult) -> None:
        async with self.services.sessionmaker.begin() as session:
            session.add(
                Review(
                    run_id=self.run_id,
                    task_id=task.id,
                    verdict=review.verdict,
                    findings=[f.model_dump() for f in review.findings],
                )
            )
            await append_event(
                session,
                self.run_id,
                EventType.REVIEW_COMPLETED,
                task_id=task.id,
                agent_id="reviewer",
                payload={"verdict": review.verdict, "findings": len(review.findings)},
            )

    async def _finish_task(
        self,
        task_id: uuid.UUID,
        status: str,
        *,
        summary: str | None = None,
        error: str | None = None,
        reason: str | None = None,
    ) -> None:
        async with self.services.sessionmaker.begin() as session:
            task = await session.get(Task, task_id)
            assert task is not None
            if task.status != status:
                await store.transition(session, task_id, status)
            if status == "completed":
                await append_event(
                    session, self.run_id, EventType.TASK_COMPLETED, task_id=task_id,
                    payload={"summary": (summary or "")[:500] or None},
                )  # fmt: skip
            elif status == "failed":
                await append_event(
                    session, self.run_id, EventType.TASK_FAILED, task_id=task_id,
                    payload={"error": (error or "unknown error")[:500]},
                )  # fmt: skip
            else:
                await append_event(
                    session, self.run_id, EventType.TASK_BLOCKED, task_id=task_id,
                    payload={"reason": (reason or "blocked")[:500]},
                )  # fmt: skip

    async def _self_log(
        self, task: Task, outcome: str, notes: str, check: CheckOutcome | None
    ) -> None:
        text = (
            f"Task: {task.title}\nOutcome: {outcome}\n"
            f"Check: {_check_summary(check) if check else 'n/a'}\nNotes: {notes[:800]}"
        )
        await self._memory(
            "add_self_log",
            run_id=str(self.run_id),
            task_id=str(task.id),
            role="coder",
            outcome=outcome,
            text=text,
        )

    async def finalize(self) -> None:
        assert self.worktree is not None and self.base is not None
        assert self.workspace_root is not None
        changes = await run_in_threadpool(git.diff, self.worktree, self.base)
        async with self.services.sessionmaker() as session:
            statuses = list(
                await session.scalars(select(Task.status).where(Task.run_id == self.run_id))
            )
        completed = statuses.count("completed")

        if completed == 0:
            # Changes that no task got accepted are not offered for approval.
            detail = (
                f"{len(changes)} file(s) were changed but none passed checks/review"
                if changes
                else "no files were changed"
            )
            raise RunAborted(f"No task was completed; {detail}.")
        if changes:
            async with self.services.sessionmaker.begin() as session:
                for change in changes:
                    original = await run_in_threadpool(
                        git.show_file, self.workspace_root, self.base, change.path
                    )
                    session.add(
                        FileChange(
                            run_id=self.run_id,
                            path=change.path,
                            change_type=change.change_type,
                            base_hash=content_hash(original.encode())
                            if original is not None
                            else None,
                            diff=change.diff,
                        )
                    )
            await self.emit(EventType.DIFF_READY, files=[c.path for c in changes])
            await set_status(self.services, self.run_id, "awaiting_approval")
        else:
            await set_status(self.services, self.run_id, "completed", finished=True)
            await self.emit(
                EventType.RUN_COMPLETED, summary="The tasks finished without changing any files."
            )
        return

    async def cleanup(self, *, remove_worktree: bool) -> None:
        if self.mcp is not None:
            await run_in_threadpool(self.mcp.close)
        if remove_worktree and self.worktree is not None and self.workspace_root is not None:
            await run_in_threadpool(git.remove_worktree, self.workspace_root, self.worktree)


# ---------- ADK agents ----------


@dataclass
class TaskLoopState:
    """Shared by the agents of one task's reflection loop."""

    task: Task
    worker: str
    rounds: int
    standards: list[str]
    lessons: list[str]
    round: int = 0
    feedback: str | None = None
    summary: str = ""
    outcome: str = ""  # "no_change" | "checked"
    check: CheckOutcome | None = None
    review: roles.ReviewResult | None = None
    review_prompt: str = ""
    # Set when every provider failed for the Reviewer on every attempt: no verdict exists.
    review_unavailable: str | None = None
    finished: bool = False


def _review_fallback(errors: list[str]) -> roles.ReviewResult:
    return roles.ReviewResult(
        verdict="blocked", summary="The Reviewer did not produce a valid verdict."
    )


class RunStep(BaseAgent):
    """A deterministic run step (custom ADK agent) wrapping one RunWorkflow method."""

    _fn: Callable[[], Awaitable[None]] = PrivateAttr()

    def __init__(self, name: str, description: str, fn: Callable[[], Awaitable[None]]) -> None:
        super().__init__(name=name, description=description)
        self._fn = fn

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        await self._fn()
        yield state_event(self, ctx, **{f"{self.name}_done": True})


class CoderStep(BaseAgent):
    """CrewAI Coder edits files through the MCP tools; then the sandbox check runs."""

    _workflow: "RunWorkflow" = PrivateAttr()
    _state: TaskLoopState = PrivateAttr()

    def __init__(self, workflow: "RunWorkflow", state: TaskLoopState) -> None:
        super().__init__(
            name="coder",
            description="CrewAI Coder: edits files via MCP tools, then the sandbox check runs.",
        )
        self._workflow, self._state = workflow, state

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        wf, st = self._workflow, self._state
        st.round += 1
        st.check, st.review = None, None
        before = await wf._worktree_fingerprint()
        st.summary = await wf._crew(
            "coder",
            roles.coder_prompt(
                title=st.task.title,
                description=st.task.description,
                criteria=st.task.acceptance_criteria,
                target_files=st.task.target_files,
                standards=st.standards,
                lessons=st.lessons,
                feedback=st.feedback,
            ),
            "A short summary of the changes and the final check result",
            agent_id=st.worker,
            parent="coder",
            task_id=st.task.id,
        )
        # Agents' claims are not evidence: a round that changed no files did nothing,
        # whatever its final answer says.
        if await wf._worktree_fingerprint() == before:
            st.outcome, st.feedback = "no_change", NO_CHANGES_FEEDBACK
        else:
            st.outcome = "checked"
            st.check = await wf._run_check(st.task.id)
        yield state_event(
            self,
            ctx,
            round=st.round,
            outcome=st.outcome,
            check_accepted=bool(st.check and _accepted(st.check)),
        )


class ReviewGate(BaseAgent):
    """Runs the ADK Reviewer when the round produced checked changes and review is required."""

    _workflow: "RunWorkflow" = PrivateAttr()
    _state: TaskLoopState = PrivateAttr()

    def __init__(self, workflow: "RunWorkflow", state: TaskLoopState) -> None:
        llm = HexAdkLlm(
            router=workflow.services.providers,
            ctx=CallContext(
                run_id=workflow.run_id,
                task_id=state.task.id,
                agent_id="reviewer",
                complexity=workflow.complexity,
            ),
            purpose="reviewer",
            max_tokens=2048,
        )
        reviewer = LlmAgent(
            name="reviewer",
            description="ADK Reviewer: judges the change against the acceptance criteria.",
            model=llm,
            instruction=lambda ctx: state.review_prompt,
            include_contents="none",
            output_schema=roles.ReviewResult,
            output_key="review",
            after_model_callback=schema_guard(
                roles.ReviewResult, llm, key="review", fallback=_review_fallback
            ),
            on_model_error_callback=model_error_fallback(
                roles.ReviewResult, key="review", fallback=_review_fallback
            ),
        )
        super().__init__(
            name="review_gate",
            description="Reviews checked changes when the strategy requires review.",
            sub_agents=[reviewer],
        )
        self._workflow, self._state = workflow, state

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        wf, st = self._workflow, self._state
        if st.outcome != "checked" or not wf.requires_review:
            yield state_event(self, ctx, review_skipped=True)
            return
        assert st.check is not None
        async with wf.services.sessionmaker.begin() as session:
            await store.transition(session, st.task.id, "review")
        await wf.emit(
            EventType.REVIEW_STARTED, task_id=st.task.id, agent_id="reviewer", reviewer="reviewer"
        )
        st.review_prompt = await wf._review_prompt(st.task, st.check)
        st.review_unavailable = None
        # A provider outage is not a verdict: retry the review after a pause (rate limits
        # and cooldowns clear within a minute) instead of blocking working code.
        delays = [0.0, *wf.services.settings.review_retry_delays_s]
        for attempt, delay in enumerate(delays):
            if delay:
                await asyncio.sleep(delay)
            async for event in self.sub_agents[0].run_async(ctx):
                yield event
            errors = ctx.session.state.get("review_schema_errors") or []
            outage = ctx.session.state.get("review_schema_status") == "fallback" and any(
                str(e).startswith("provider error") for e in errors
            )
            if not outage:
                break
            logger.warning(
                "review of task %s: providers unavailable (attempt %d/%d)",
                st.task.id,
                attempt + 1,
                len(delays),
            )
        else:
            st.review, st.review_unavailable = None, str(errors[0])[:300]
            return
        st.review = roles.ReviewResult.model_validate(ctx.session.state["review"])
        await wf._record_review(st.task, st.review)


class DecideStep(BaseAgent):
    """Applies the acceptance rules; escalates to end the loop once the task is decided."""

    _workflow: "RunWorkflow" = PrivateAttr()
    _state: TaskLoopState = PrivateAttr()

    def __init__(self, workflow: "RunWorkflow", state: TaskLoopState) -> None:
        super().__init__(
            name="decide",
            description="Accepts, retries or stops the task from real check and review results.",
        )
        self._workflow, self._state = workflow, state

    async def _finish(self, ctx, status: str, **detail: str) -> Event:
        wf, st = self._workflow, self._state
        await wf._finish_task(st.task.id, status, **detail)
        log_outcome = status if status in ("completed", "blocked") else "not_accepted"
        await wf._self_log(st.task, log_outcome, st.feedback or st.summary, st.check)
        st.finished = True
        return escalate_event(self, ctx, decision=status)

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        wf, st = self._workflow, self._state
        last = st.round >= st.rounds

        if st.outcome == "no_change":
            if last:
                yield await self._finish(
                    ctx, "failed", error=f"no file changes after {st.rounds} attempts"
                )
            else:
                yield state_event(self, ctx, decision="retry")
            return

        check = st.check
        assert check is not None
        if not wf.requires_review:
            if _accepted(check):
                yield await self._finish(ctx, "completed", summary=st.summary)
                return
            st.feedback = _check_feedback(check)
            if last:
                yield await self._finish(
                    ctx, "failed", error=f"checks still failing after {st.rounds} attempts"
                )
            else:
                yield state_event(self, ctx, decision="retry")
            return

        if st.review_unavailable:
            attempts = 1 + len(wf.services.settings.review_retry_delays_s)
            yield await self._finish(
                ctx,
                "failed",
                error=f"review unavailable after {attempts} attempts (all providers failed): "
                f"{st.review_unavailable}",
            )
            return
        review = st.review
        assert review is not None
        if review.verdict == "approved" and _accepted(check):
            yield await self._finish(ctx, "completed", summary=st.summary)
            return
        if review.verdict == "blocked":
            yield await self._finish(ctx, "blocked", reason=review.summary or "reviewer")
            return
        st.feedback = "\n".join(
            [f"- {f.file or ''}:{f.line or ''} {f.message}" for f in review.findings]
            + ([_check_feedback(check)] if not _accepted(check) else [])
        )
        async with wf.services.sessionmaker.begin() as session:
            await store.transition(session, st.task.id, "changes_requested")
            if not last:
                await store.transition(session, st.task.id, "running")
        if last:
            yield await self._finish(
                ctx, "blocked", reason=f"not accepted after {st.rounds} review rounds"
            )
        else:
            yield state_event(self, ctx, decision="retry")


def reflection_loop(workflow: "RunWorkflow", state: TaskLoopState) -> LoopAgent:
    """Reflection pattern: Coder (CrewAI) -> review gate (ADK Reviewer) -> decide."""
    return LoopAgent(
        name="reflection_loop",
        description="Code, check and review until accepted or out of rounds.",
        sub_agents=[
            CoderStep(workflow, state),
            ReviewGate(workflow, state),
            DecideStep(workflow, state),
        ],
        max_iterations=state.rounds,
    )


def run_orchestrator(workflow: "RunWorkflow", *, requires_planning: bool) -> SequentialAgent:
    return SequentialAgent(
        name="run_orchestrator",
        description="Prepare an isolated worktree, plan, execute tasks, and produce the diff.",
        sub_agents=[
            RunStep("prepare", "Snapshot, worktree and MCP workspace server.", workflow.prepare),
            RunStep(
                "plan",
                "Planner crew (or a single task for low complexity) fills the Blackboard.",
                workflow.plan if requires_planning else workflow.single_task,
            ),
            RunStep("execute", "Worker pool runs each task's reflection loop.", workflow.execute),
            RunStep("finalize", "Diff, file changes, and approval gate.", workflow.finalize),
        ],
    )


async def execute_run(
    services: Services, run_id: uuid.UUID, *, requires_planning: bool, requires_review: bool
) -> None:
    """Run the ADK orchestrator; failures mark the run failed with a run_failed event."""
    workflow = RunWorkflow(services, run_id, requires_review=requires_review)
    succeeded = False
    try:
        await run_adk(
            workflow.telemetry.instrument(
                run_orchestrator(workflow, requires_planning=requires_planning)
            ),
            message=f"Execute run {run_id}",
        )
        succeeded = True
    except Exception as exc:
        exc = _innermost(exc)
        await workflow.telemetry.abort_open(error=str(exc))
        if not isinstance(exc, RunAborted):
            logger.exception("run %s failed", run_id, exc_info=exc)
        async with services.sessionmaker.begin() as session:
            await session.execute(
                Task.__table__.update()
                .where(Task.run_id == run_id, Task.status.in_(store.OPEN_STATUSES))
                .values(status="cancelled")
            )
        await set_status(services, run_id, "failed", finished=True)
        async with services.sessionmaker.begin() as session:
            await append_event(
                session, run_id, EventType.RUN_FAILED, payload={"error": str(exc)[:1000]}
            )
    finally:
        # Keep the worktree while its diff awaits review; otherwise there is nothing to keep.
        async with services.sessionmaker() as session:
            run = await session.get(Run, run_id)
            keep = succeeded and run is not None and run.status == "awaiting_approval"
        await workflow.cleanup(remove_worktree=not keep)


def _innermost(exc: BaseException) -> BaseException:
    """ADK wraps agent failures (e.g. DynamicNodeFailError.error); unwrap to the cause."""
    seen = set()
    while id(exc) not in seen:
        seen.add(id(exc))
        inner = getattr(exc, "error", None)
        if isinstance(inner, BaseException):
            exc = inner
            continue
        break
    return exc


NO_CHANGES_FEEDBACK = (
    "Your previous attempt did not change any files. Describing code in your answer changes "
    "nothing: you must call write_file or replace_in_file to create or edit the files, then "
    "run the `test` check."
)

# Test runners that found nothing to run: node's TAP ("# tests 0") and spec ("ℹ tests 0")
# reporters, Python's unittest ("Ran 0 tests").
_NO_TESTS = re.compile(r"(?m)^(?:\S+\s+)?tests 0\s*$|\bRan 0 tests\b")


def _ran_no_tests(check: CheckOutcome) -> bool:
    return bool(_NO_TESTS.search(check.output_tail))


def _accepted(check: CheckOutcome) -> bool:
    """A check counts only if it passed *and* actually ran tests; exit 0 with no tests proves
    nothing (`node --test` succeeds in an empty project)."""
    return check.passed and not _ran_no_tests(check)


def _check_summary(check: CheckOutcome | None) -> str:
    if check is None:
        return "not run"
    if check.exit_code is None:
        return f"{check.name}: did not complete ({check.error})"
    if check.passed and _ran_no_tests(check):
        status = "exited 0 but ran NO tests (add *.test.js files using node:test)"
    else:
        status = "passed" if check.passed else f"FAILED (exit {check.exit_code})"
    return f"{check.name}: {status}\n{check.output_tail[-1500:]}"


def _check_feedback(check: CheckOutcome) -> str:
    return f"The `{check.name}` check is failing:\n{_check_summary(check)}"
