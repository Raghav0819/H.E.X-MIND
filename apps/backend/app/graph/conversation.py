"""Conversation graph (LangGraph): build context -> Router -> policy -> answer | clarify | run.

The Router model proposes a route; `apply_policy` decides it; the conditional edge follows the
policy result. Runs are executed by the run graph in the background.
"""

import uuid
from pathlib import Path
from typing import Any, TypedDict

from fastapi.concurrency import run_in_threadpool
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.db.models import Conversation, Project, RouterDecision, Run
from app.events.log import EventType, append_event
from app.graph.services import Services
from app.providers.base import ChatMessage, LLMRequest
from app.router.classifier import classify
from app.router.policy import apply_policy
from app.router.schemas import Mode, RoutePlan
from app.workspace import git

ANSWER_PROMPT = """You are H.E.X Mind, an AI pair programmer inside the developer's IDE.
Answer the developer's latest message using the project context below. File contents in the
context were read from disk just now and are the source of truth; earlier messages may be out
of date. Reference files by path. If the context does not contain what you need, say which
files you would need to see instead of guessing. You cannot modify files in this reply, so never
claim to have changed anything. Be concise and use Markdown."""

ASK_MODE_CHANGE_NOTE = """The developer asked for a code change while in Ask mode. Explain what
would need to change and where, and suggest switching to Edit mode to have the agents do it."""


class ConversationState(TypedDict, total=False):
    conversation_id: uuid.UUID
    project_id: uuid.UUID
    message_id: uuid.UUID
    content: str
    mode: Mode
    context_text: str
    context_sources: dict[str, Any]
    plan: RoutePlan
    router: dict[str, Any]
    decision_id: uuid.UUID
    reply: str
    reply_kind: str
    llm: dict[str, Any] | None
    run_id: uuid.UUID | None


def build_conversation_graph(services: Services):
    async def build_context(state: ConversationState) -> dict:
        async with services.sessionmaker() as session:
            project = await session.get(Project, state["project_id"])
            conversation = await session.get(Conversation, state["conversation_id"])
            assert project is not None and conversation is not None
            bundle = await services.context.build(
                session,
                project=project,
                conversation=conversation,
                message=state["content"],
                exclude_message_id=state["message_id"],
            )
        return {"context_text": bundle.render(), "context_sources": bundle.sources()}

    async def route(state: ConversationState) -> dict:
        result = await classify(
            services.providers,
            message=state["content"],
            mode=state["mode"],
            context=state["context_text"],
        )
        plan = apply_policy(
            result.decision, state["mode"], min_confidence=services.settings.router_min_confidence
        )
        router_info = {
            "proposal": result.decision.model_dump() if result.decision else None,
            "policy": plan.model_dump(),
            "attempts": result.attempts,
            "errors": result.errors,
        }
        async with services.sessionmaker.begin() as session:
            row = RouterDecision(
                message_id=state["message_id"],
                decision=router_info,
                valid=result.decision is not None,
                fallback_used=plan.fallback_used,
                provider=result.provider,
                model=result.model,
            )
            session.add(row)
            await session.flush()
            decision_id = row.id
        return {"plan": plan, "router": router_info, "decision_id": decision_id}

    async def answer(state: ConversationState) -> dict:
        system = ANSWER_PROMPT
        if state["plan"].policy_note and state["mode"] == "ask":
            system += "\n\n" + ASK_MODE_CHANGE_NOTE
        result = await services.providers.complete(
            LLMRequest(
                purpose="chat",
                messages=[
                    ChatMessage(role="system", content=system),
                    ChatMessage(
                        role="user",
                        content=f"{state['context_text']}\n\n---\nDeveloper:\n{state['content']}",
                    ),
                ],
                max_tokens=1200,
            )
        )
        llm = {
            "provider": result.provider,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }
        if not result.ok or not result.content:
            return {
                "reply": f"The model call failed, so there is no answer: {result.error}",
                "reply_kind": "error",
                "llm": llm,
            }
        return {"reply": result.content, "reply_kind": "answer", "llm": llm}

    async def clarify(state: ConversationState) -> dict:
        question = state["plan"].clarification_question or "Could you clarify the request?"
        return {"reply": question, "reply_kind": "clarification", "llm": None}

    async def start_run(state: ConversationState) -> dict:
        plan = state["plan"]
        async with services.sessionmaker() as session:
            project = await session.get(Project, state["project_id"])
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
                .where(Run.conversation_id == state["conversation_id"])
                .order_by(Run.created_at.desc())
                .limit(1)
            )
            run = Run(
                project_id=state["project_id"],
                conversation_id=state["conversation_id"],
                parent_run_id=parent,
                triggering_message_id=state["message_id"],
                title=_title(state["content"]),
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
                    "triggering_message_id": str(state["message_id"]),
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
            decision = await session.get(RouterDecision, state["decision_id"])
            assert decision is not None
            decision.run_id = run.id
            run_id = run.id

        services.launch_run(
            run_id,
            requires_planning=plan.requires_planning,
            requires_review=plan.requires_review,
        )
        reply = (
            f"Started a **{plan.complexity}**-complexity run ({plan.strategy}). The agents work "
            "in an isolated copy of the workspace; **your files are not changed** until you "
            "review and apply the diff."
        )
        return {"reply": reply, "reply_kind": "run_started", "llm": None, "run_id": run_id}

    graph = StateGraph(ConversationState)
    graph.add_node("build_context", build_context)
    graph.add_node("route", route)
    graph.add_node("answer", answer)
    graph.add_node("clarify", clarify)
    graph.add_node("start_run", start_run)

    graph.add_edge(START, "build_context")
    graph.add_edge("build_context", "route")
    graph.add_conditional_edges(
        "route",
        lambda s: s["plan"].route,
        {"answer": "answer", "clarify": "clarify", "run": "start_run"},
    )
    for node in ("answer", "clarify", "start_run"):
        graph.add_edge(node, END)
    return graph.compile()


def _title(content: str) -> str:
    first_line = content.strip().splitlines()[0] if content.strip() else "Untitled"
    return first_line if len(first_line) <= 80 else first_line[:77] + "…"
