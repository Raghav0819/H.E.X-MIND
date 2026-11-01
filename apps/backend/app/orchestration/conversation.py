"""Conversation flow on Google ADK: build context -> Router -> policy -> answer | clarify | run.

- `ConversationAgent` (custom ADK BaseAgent) owns the flow and the deterministic steps.
- `router` is an ADK LlmAgent with Pydantic `output_schema=RouterDecision`, guarded so invalid
  output is repaired once and otherwise replaced by a fallback (see `adk.schema_guard`).
- The policy (`apply_policy`) decides the route; the Router only proposes it.
- `answer` is an ADK LlmAgent for Ask-style replies.
Runs are executed in the background by the run orchestrator (`orchestration.run`).

All model calls go through ProviderRouter via HexAdkLlm, so they are logged and fall back
across providers like every other call.
"""

import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from fastapi.concurrency import run_in_threadpool
from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from pydantic import PrivateAttr
from sqlalchemy import select

from app.agents.adk_llm import HexAdkLlm
from app.db.models import Conversation, Project, Run
from app.db.models import RouterDecision as RouterDecisionRow
from app.events.log import EventType, append_event
from app.orchestration.adk import (
    model_error_fallback,
    run_adk,
    schema_guard,
    state_event,
    user_message_from_state,
)
from app.orchestration.services import Services
from app.providers.router import CallContext
from app.router.classifier import SYSTEM_PROMPT as ROUTER_PROMPT
from app.router.policy import apply_policy
from app.router.schemas import Mode, RoutePlan, RouterDecision
from app.workspace import git

ANSWER_PROMPT = """You are H.E.X Mind, an AI pair programmer inside the developer's IDE.
Answer the developer's latest message using the project context below. File contents in the
context were read from disk just now and are the source of truth; earlier messages may be out
of date. Reference files by path. If the context does not contain what you need, say which
files you would need to see instead of guessing. You cannot modify files in this reply, so never
claim to have changed anything. Be concise and use Markdown."""

ASK_MODE_CHANGE_NOTE = """The developer asked for a code change while in Ask mode. Explain what
would need to change and where, and suggest switching to Edit mode to have the agents do it."""

# Stored when the Router output could not be used; policy then applies its deterministic fallback.
_INVALID_ROUTER = RouterDecision(
    request_type="clarification",
    complexity="medium",
    confidence=0.0,
    reason="Router output invalid",
    execution_strategy="plan_execute_review",
    requires_planning=True,
    requires_review=True,
)


def _router_fallback(errors: list[str]) -> RouterDecision:
    return _INVALID_ROUTER


class ConversationAgent(BaseAgent):
    """Root agent for one user message."""

    _services: Services = PrivateAttr()
    _turn: dict[str, Any] = PrivateAttr()
    _router_llm: HexAdkLlm = PrivateAttr()
    _answer_llm: HexAdkLlm = PrivateAttr()

    def __init__(self, services: Services, turn: dict[str, Any]) -> None:
        router_llm = HexAdkLlm(
            router=services.providers, ctx=CallContext(), purpose="router", max_tokens=1500
        )
        answer_llm = HexAdkLlm(
            router=services.providers, ctx=CallContext(), purpose="chat", max_tokens=1200
        )
        router = LlmAgent(
            name="router",
            description="Classifies the request: type, complexity, strategy.",
            model=router_llm,
            instruction=lambda ctx: (
                f"{ROUTER_PROMPT}\n\n{ctx.state.get('context_text', '')}\n\n"
                f"Selected mode: {ctx.state.get('mode', 'auto')}"
            ),
            include_contents="none",
            output_schema=RouterDecision,
            output_key="router_decision",
            after_model_callback=schema_guard(
                RouterDecision, router_llm, key="router", fallback=_router_fallback
            ),
            on_model_error_callback=model_error_fallback(
                RouterDecision, key="router", fallback=_router_fallback
            ),
        )
        answer = LlmAgent(
            name="answer",
            description="Answers questions about the project without changing files.",
            model=answer_llm,
            instruction=lambda ctx: (
                ANSWER_PROMPT
                + ("\n\n" + ASK_MODE_CHANGE_NOTE if ctx.state.get("ask_change_note") else "")
            ),
            include_contents="none",
            before_model_callback=user_message_from_state("context_text"),
            output_key="answer_text",
        )
        super().__init__(
            name="conversation",
            description="Routes a developer message and answers, clarifies or starts a run.",
            sub_agents=[router, answer],
        )
        self._services = services
        self._turn = turn
        self._router_llm = router_llm
        self._answer_llm = answer_llm

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        services, turn = self._services, self._turn
        router, answer = self.sub_agents

        # 1. Context (deterministic): files read fresh from disk, history, prior runs.
        async with services.sessionmaker() as session:
            project = await session.get(Project, turn["project_id"])
            conversation = await session.get(Conversation, turn["conversation_id"])
            assert project is not None and conversation is not None
            bundle = await services.context.build(
                session,
                project=project,
                conversation=conversation,
                message=turn["content"],
                exclude_message_id=turn["message_id"],
            )
        turn["context_sources"] = bundle.sources()
        yield state_event(self, ctx, context_text=bundle.render(), mode=turn["mode"])

        # 2. Router (ADK LlmAgent, Pydantic output) -> 3. policy (deterministic).
        async for event in router.run_async(ctx):
            yield event
        state = ctx.session.state
        status = state.get("router_schema_status", "valid")
        decision = (
            RouterDecision.model_validate(state["router_decision"])
            if status != "fallback" and state.get("router_decision")
            else None
        )
        plan = apply_policy(
            decision, turn["mode"], min_confidence=services.settings.router_min_confidence
        )
        last = self._router_llm.last_result
        router_info = {
            "proposal": decision.model_dump() if decision else None,
            "policy": plan.model_dump(),
            "schema_status": status,
            "attempts": {"valid": 1, "repaired": 2, "fallback": 2}.get(status, 1),
            "errors": state.get("router_schema_errors", []),
        }
        async with services.sessionmaker.begin() as session:
            row = RouterDecisionRow(
                message_id=turn["message_id"],
                decision=router_info,
                valid=decision is not None,
                fallback_used=plan.fallback_used,
                provider=last.provider if last else None,
                model=last.model if last else None,
            )
            session.add(row)
            await session.flush()
            turn["decision_id"] = row.id
        turn["plan"] = plan
        turn["router"] = router_info
        yield state_event(
            self,
            ctx,
            route=plan.route,
            ask_change_note=bool(plan.policy_note and turn["mode"] == "ask"),
        )

        # 4. Branch on the policy's route.
        if plan.route == "answer":
            self._answer_llm._ctx = CallContext(complexity=plan.complexity)
            try:
                async for event in answer.run_async(ctx):
                    yield event
                text = ctx.session.state.get("answer_text") or ""
                turn.update(reply=text, reply_kind="answer" if text else "error")
                if not text:
                    turn["reply"] = "The model returned an empty answer."
            except Exception as exc:  # provider failure: report it, never invent an answer
                turn.update(
                    reply=f"The model call failed, so there is no answer: {_error_text(exc)}",
                    reply_kind="error",
                )
            result = self._answer_llm.last_result
            turn["llm"] = (
                {
                    "provider": result.provider,
                    "model": result.model,
                    "latency_ms": result.latency_ms,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                }
                if result
                else None
            )
        elif plan.route == "clarify":
            turn.update(
                reply=plan.clarification_question or "Could you clarify the request?",
                reply_kind="clarification",
                llm=None,
            )
        else:
            turn.update(await _start_run(services, turn, plan))
        yield state_event(self, ctx, reply_kind=turn["reply_kind"])


async def run_conversation(
    services: Services,
    *,
    conversation_id: uuid.UUID,
    project_id: uuid.UUID,
    message_id: uuid.UUID,
    content: str,
    mode: Mode,
) -> dict[str, Any]:
    """Run one message through the ADK conversation flow. Returns reply, reply_kind, plan,
    decision_id, context_sources, llm and run_id."""
    turn: dict[str, Any] = {
        "conversation_id": conversation_id,
        "project_id": project_id,
        "message_id": message_id,
        "content": content,
        "mode": mode,
        "llm": None,
        "run_id": None,
    }
    await run_adk(ConversationAgent(services, turn), message=content)
    return turn


async def _start_run(services: Services, turn: dict[str, Any], plan: RoutePlan) -> dict[str, Any]:
    async with services.sessionmaker() as session:
        project = await session.get(Project, turn["project_id"])
        assert project is not None
    if not await run_in_threadpool(git.is_repo, Path(project.workspace_path)):
        return {
            "reply": (
                "This workspace is not a Git repository, so agents can't make changes yet. "
                "Initialize Git for the project (the **No Git** badge in the top bar), then "
                "send the request again. Agents work in an isolated Git worktree so every "
                "change can be reviewed and reverted."
            ),
            "reply_kind": "error",
            "llm": None,
            "run_id": None,
        }
    async with services.sessionmaker.begin() as session:
        parent = await session.scalar(
            select(Run.id)
            .where(Run.conversation_id == turn["conversation_id"])
            .order_by(Run.created_at.desc())
            .limit(1)
        )
        run = Run(
            project_id=turn["project_id"],
            conversation_id=turn["conversation_id"],
            parent_run_id=parent,
            triggering_message_id=turn["message_id"],
            title=_title(turn["content"]),
            complexity=plan.complexity,
            strategy=plan.strategy,
        )
        session.add(run)
        await session.flush()
        await append_event(
            session,
            run.id,
            EventType.RUN_CREATED,
            payload={
                "title": run.title,
                "parent_run_id": str(parent) if parent else None,
                "triggering_message_id": str(turn["message_id"]),
            },
        )
        await append_event(
            session,
            run.id,
            EventType.ROUTER_DECIDED,
            agent_id="router",
            payload={
                "request_type": plan.request_type,
                "complexity": plan.complexity,
                "confidence": plan.confidence,
                "route": plan.route,
                "strategy": plan.strategy,
                "fallback_used": plan.fallback_used,
            },
        )
        # The Router's structured output was validated before the run existed; record that
        # check in the run's own log so every run's schema checks start with it.
        await append_event(
            session,
            run.id,
            EventType.SCHEMA_VALIDATED,
            agent_id="router",
            payload={
                "agent": "router",
                "schema_name": "RouterDecision",
                "status": turn["router"]["schema_status"],
                "errors": [str(e)[:300] for e in turn["router"]["errors"]],
            },
        )
        decision = await session.get(RouterDecisionRow, turn["decision_id"])
        assert decision is not None
        decision.run_id = run.id
        run_id = run.id

    services.launch_run(
        run_id, requires_planning=plan.requires_planning, requires_review=plan.requires_review
    )
    reply = (
        f"Started a **{plan.complexity}**-complexity run ({plan.strategy}). The agents work "
        "in an isolated copy of the workspace; **your files are not changed** until you "
        "review and apply the diff."
    )
    return {"reply": reply, "reply_kind": "run_started", "llm": None, "run_id": run_id}


def _error_text(exc: BaseException) -> str:
    # ADK may wrap the provider failure; report the innermost message.
    while getattr(exc, "error", None) is not None and isinstance(exc.error, BaseException):
        exc = exc.error
    while exc.__cause__ is not None:
        exc = exc.__cause__
    return str(exc)


def _title(content: str) -> str:
    first_line = content.strip().splitlines()[0] if content.strip() else "Untitled"
    return first_line if len(first_line) <= 80 else first_line[:77] + "…"
