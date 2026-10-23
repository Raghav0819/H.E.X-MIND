"""Run graph (LangGraph). Edges follow the routing policy; the worker nodes are M2 stubs.

The stubs perform no planning, coding or review. They move the run through its real status
transitions and emit `run_status_changed` events marked `stub: true`, so the event pipeline can
be exercised end to end without presenting fake agent output. CrewAI workers replace them in M3.
"""

import uuid
from datetime import UTC, datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.db.models import Run
from app.events.log import EventType, append_event
from app.graph.services import Services

STUB_SUMMARY = "No changes were made: worker agents (Planner, Coder, Reviewer) arrive in M3."


class RunState(TypedDict):
    run_id: uuid.UUID
    requires_planning: bool
    requires_review: bool
    visited: list[str]


async def set_status(
    services: Services, run_id: uuid.UUID, status: str, *, stub: bool, finished: bool = False
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
            payload={"status": status, "previous": previous, "stub": stub},
        )


def build_run_graph(services: Services):
    def stub_node(name: str, status: str):
        async def node(state: RunState) -> dict:
            await set_status(services, state["run_id"], status, stub=True)
            return {"visited": [*state["visited"], name]}

        return node

    async def finalize(state: RunState) -> dict:
        await set_status(services, state["run_id"], "completed", stub=True, finished=True)
        async with services.sessionmaker.begin() as session:
            await append_event(
                session,
                state["run_id"],
                EventType.RUN_COMPLETED,
                payload={"summary": STUB_SUMMARY, "stub": True},
            )
        return {"visited": [*state["visited"], "finalize"]}

    graph = StateGraph(RunState)
    graph.add_node("plan", stub_node("plan", "planning"))
    graph.add_node("execute", stub_node("execute", "executing"))
    graph.add_node("review", stub_node("review", "reviewing"))
    graph.add_node("finalize", finalize)

    graph.add_conditional_edges(
        START, lambda s: "plan" if s["requires_planning"] else "execute", ["plan", "execute"]
    )
    graph.add_edge("plan", "execute")
    graph.add_conditional_edges(
        "execute",
        lambda s: "review" if s["requires_review"] else "finalize",
        ["review", "finalize"],
    )
    graph.add_edge("review", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


async def execute_run(
    services: Services, run_id: uuid.UUID, *, requires_planning: bool, requires_review: bool
) -> RunState:
    """Run the graph; any failure marks the run failed with a run_failed event."""
    graph = build_run_graph(services)
    try:
        return await graph.ainvoke(
            {
                "run_id": run_id,
                "requires_planning": requires_planning,
                "requires_review": requires_review,
                "visited": [],
            }
        )
    except Exception as exc:
        await set_status(services, run_id, "failed", stub=False, finished=True)
        async with services.sessionmaker.begin() as session:
            await append_event(session, run_id, EventType.RUN_FAILED, payload={"error": str(exc)})
        raise
