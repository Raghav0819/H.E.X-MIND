"""Run graph (LangGraph): prepare -> [plan] -> execute -> finalize.

- prepare:  snapshot the user's workspace, create an isolated git worktree, start the MCP
            workspace server bound to it.
- plan:     the Planner breaks the request into Blackboard tasks (medium/high complexity);
            low complexity gets a single task.
- execute:  a pool of workers claims tasks atomically. Per task: Coder -> sandbox check ->
            Reviewer (when required), with up to `review_max_rounds` change rounds.
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
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict

from fastapi.concurrency import run_in_threadpool
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.agents import roles
from app.agents.llm import HexLLM
from app.agents.mcp_bridge import McpWorkspace
from app.agents.tools import CODER, READ_ONLY, REVIEW, make_tools
from app.blackboard import store
from app.context.workspace_scan import list_files, mentioned_files
from app.db.models import CheckResult, FileChange, Message, Project, Review, Run, Task
from app.events.log import EventType, append_event
from app.graph.services import Services
from app.memory.store import safely
from app.providers.router import CallContext
from app.sandbox.runner import CheckOutcome
from app.workspace import git
from app.workspace.files import content_hash

logger = logging.getLogger(__name__)

MAX_DIFF_FOR_REVIEW = 12_000
_standards_seeded = False


class RunAborted(RuntimeError):
    """A run cannot proceed for a reason the user can fix (shown in run_failed)."""


class RunState(TypedDict):
    run_id: uuid.UUID
    requires_planning: bool
    requires_review: bool


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
    mcp: McpWorkspace | None = None

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

    def _llm(self, purpose: str, task_id: uuid.UUID | None, agent_id: str) -> HexLLM:
        return HexLLM(
            router=self.services.providers,
            loop=self.loop,
            ctx=CallContext(run_id=self.run_id, task_id=task_id, agent_id=agent_id),
            purpose=purpose,  # type: ignore[arg-type]
        )

    def _tools(self, names: tuple[str, ...], task_id: uuid.UUID | None, agent_id: str):
        assert self.mcp is not None

        def listener(name: str, args: dict[str, Any], ok: bool, text: str) -> None:
            # Called on a CrewAI worker thread: record the event on the server loop.
            future = asyncio.run_coroutine_threadsafe(
                self.emit(
                    EventType.TOOL_CALLED,
                    task_id=task_id,
                    agent_id=agent_id,
                    tool=name,
                    ok=ok,
                    summary=_tool_summary(name, args, text),
                ),
                self.loop,
            )
            future.result(timeout=30)

        return make_tools(self.mcp, names, listener)

    async def _memory(self, method: str, *args: Any, **kwargs: Any) -> Any:
        memory = self.services.memory
        if memory is None:
            return []
        return await run_in_threadpool(safely, getattr(memory, method), *args, **kwargs)

    # ---------- nodes ----------

    async def prepare(self, state: RunState) -> dict:
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
        return {}

    async def plan(self, state: RunState) -> dict:
        await set_status(self.services, self.run_id, "planning")
        standards = await self._memory("standards_for", self.request, k=3)
        agent = roles.planner(
            self._llm("planner", None, "planner"),
            self._tools(READ_ONLY, None, "planner"),
            self.services.settings.agent_max_iterations,
        )
        prompt = roles.planner_prompt(self.request, standards)
        plan: roles.Plan | None = None
        for _ in range(2):  # one repair attempt
            raw = await roles.run_agent(agent, prompt, "A JSON object with a tasks array")
            try:
                plan = roles.parse_json_output(raw, roles.Plan)
                break
            except roles.OutputError as exc:
                prompt += (
                    f"\n\nYour previous answer was invalid ({exc}). Answer with valid JSON only."
                )
        if plan is None:
            await self._single_task(note="The Planner's output was invalid; using a single task.")
            return {}

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
        return {}

    async def single_task(self, state: RunState) -> dict:
        await self._single_task()
        return {}

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

    async def execute(self, state: RunState) -> dict:
        await set_status(self.services, self.run_id, "executing")
        concurrency = max(1, self.services.settings.worker_concurrency)
        await asyncio.gather(*(self._worker(f"coder_{i + 1:02d}") for i in range(concurrency)))
        return {}

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
            except Exception as exc:
                logger.exception("task %s failed", task.id)
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
        standards = await self._memory("standards_for", query, k=3)
        lessons = await self._memory("self_logs_for", query, k=2, exclude_run=str(self.run_id))
        rounds = self.services.settings.review_max_rounds + 1
        feedback: str | None = None
        summary = ""
        status = "running"

        for round_number in range(1, rounds + 1):
            before = await self._worktree_fingerprint()
            agent = roles.coder(
                self._llm("coder", task.id, worker),
                self._tools(CODER, task.id, worker),
                self.services.settings.agent_max_iterations,
            )
            summary = await roles.run_agent(
                agent,
                roles.coder_prompt(
                    title=task.title,
                    description=task.description,
                    criteria=task.acceptance_criteria,
                    target_files=task.target_files,
                    standards=standards,
                    lessons=lessons,
                    feedback=feedback,
                ),
                "A short summary of the changes and the final check result",
            )
            # Agents' claims are not evidence: a round that changed no files did nothing,
            # whatever its final answer says.
            if await self._worktree_fingerprint() == before:
                feedback = NO_CHANGES_FEEDBACK
                continue
            check = await self._run_check(task.id)

            if not self.requires_review:
                if _accepted(check):
                    await self._finish_task(task.id, "completed", summary=summary)
                    await self._self_log(task, "completed", summary, check)
                    return
                feedback = _check_feedback(check)
                continue

            async with self.services.sessionmaker.begin() as session:
                await store.transition(session, task.id, "review")
            review = await self._review(task, check)
            if review.verdict == "approved" and _accepted(check):
                await self._finish_task(task.id, "completed", summary=summary)
                await self._self_log(task, "completed", summary, check)
                return
            if review.verdict == "blocked":
                await self._finish_task(task.id, "blocked", reason=review.summary or "reviewer")
                await self._self_log(task, "blocked", review.summary, check)
                return
            feedback = "\n".join(
                [f"- {f.file or ''}:{f.line or ''} {f.message}" for f in review.findings]
                + ([_check_feedback(check)] if not _accepted(check) else [])
            )
            async with self.services.sessionmaker.begin() as session:
                await store.transition(session, task.id, "changes_requested")
                status = "changes_requested"
                if round_number < rounds:
                    await store.transition(session, task.id, "running")
                    status = "running"

        if status == "changes_requested":
            reason = f"not accepted after {rounds} review rounds"
            await self._finish_task(task.id, "blocked", reason=reason)
        else:
            error = (
                f"no file changes after {rounds} attempts"
                if feedback == NO_CHANGES_FEEDBACK
                else f"checks still failing after {rounds} attempts"
            )
            await self._finish_task(task.id, "failed", error=error)
        await self._self_log(task, "not_accepted", feedback or summary, None)

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

    async def _review(self, task: Task, check: CheckOutcome) -> roles.ReviewResult:
        assert self.worktree is not None and self.base is not None
        await self.emit(
            EventType.REVIEW_STARTED, task_id=task.id, agent_id="reviewer", reviewer="reviewer"
        )
        changes = await run_in_threadpool(git.diff, self.worktree, self.base)
        relevant = [c for c in changes if not task.target_files or c.path in task.target_files]
        diff_text = "\n".join(c.diff for c in (relevant or changes))[:MAX_DIFF_FOR_REVIEW]
        standards = await self._memory("standards_for", task.title, k=2)
        agent = roles.reviewer(
            self._llm("reviewer", task.id, "reviewer"),
            self._tools(REVIEW, task.id, "reviewer"),
            self.services.settings.agent_max_iterations,
        )
        prompt = roles.reviewer_prompt(
            title=task.title,
            criteria=task.acceptance_criteria,
            diff=diff_text or "(no changes)",
            check_summary=_check_summary(check),
            standards=standards,
        )
        review: roles.ReviewResult | None = None
        for _ in range(2):
            raw = await roles.run_agent(agent, prompt, "A JSON object with verdict and findings")
            try:
                review = roles.parse_json_output(raw, roles.ReviewResult)
                break
            except roles.OutputError as exc:
                prompt += (
                    f"\n\nYour previous answer was invalid ({exc}). Answer with valid JSON only."
                )
        if review is None:
            review = roles.ReviewResult(
                verdict="blocked", summary="The Reviewer did not produce a valid verdict."
            )

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
        return review

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

    async def finalize(self, state: RunState) -> dict:
        assert self.worktree is not None and self.base is not None
        assert self.workspace_root is not None
        changes = await run_in_threadpool(git.diff, self.worktree, self.base)
        async with self.services.sessionmaker() as session:
            statuses = list(
                await session.scalars(select(Task.status).where(Task.run_id == self.run_id))
            )
        completed = statuses.count("completed")

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
        elif completed == 0:
            raise RunAborted("No task was completed and no files were changed.")
        else:
            await set_status(self.services, self.run_id, "completed", finished=True)
            await self.emit(
                EventType.RUN_COMPLETED, summary="The tasks finished without changing any files."
            )
        return {}

    async def cleanup(self, *, remove_worktree: bool) -> None:
        if self.mcp is not None:
            await run_in_threadpool(self.mcp.close)
        if remove_worktree and self.worktree is not None and self.workspace_root is not None:
            await run_in_threadpool(git.remove_worktree, self.workspace_root, self.worktree)


def build_run_graph(workflow: RunWorkflow):
    graph = StateGraph(RunState)
    graph.add_node("prepare", workflow.prepare)
    graph.add_node("plan", workflow.plan)
    graph.add_node("single_task", workflow.single_task)
    graph.add_node("execute", workflow.execute)
    graph.add_node("finalize", workflow.finalize)

    graph.add_edge(START, "prepare")
    graph.add_conditional_edges(
        "prepare",
        lambda s: "plan" if s["requires_planning"] else "single_task",
        ["plan", "single_task"],
    )
    graph.add_edge("plan", "execute")
    graph.add_edge("single_task", "execute")
    graph.add_edge("execute", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


async def execute_run(
    services: Services, run_id: uuid.UUID, *, requires_planning: bool, requires_review: bool
) -> None:
    """Run the workflow; failures mark the run failed with a run_failed event."""
    workflow = RunWorkflow(services, run_id, requires_review=requires_review)
    succeeded = False
    try:
        await build_run_graph(workflow).ainvoke(
            {
                "run_id": run_id,
                "requires_planning": requires_planning,
                "requires_review": requires_review,
            }
        )
        succeeded = True
    except Exception as exc:
        if not isinstance(exc, RunAborted):
            logger.exception("run %s failed", run_id)
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


def _tool_summary(name: str, args: dict[str, Any], text: str) -> str:
    target = args.get("path") or args.get("name") or args.get("query") or ""
    first_line = re.sub(r"\s+", " ", text.strip().splitlines()[0] if text.strip() else "")[:120]
    return f"{target}: {first_line}" if target else first_line
