"""Append-only per-run event log (plan §4.1).

`seq` is per-run and gap-free: it is taken from `runs.last_event_seq` with an UPDATE ... RETURNING
in the caller's transaction, which row-locks the run until commit, so concurrent writers to the
same run are serialized and a rolled-back event does not consume a number.
"""

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentEvent, Run


class EventType(StrEnum):
    RUN_CREATED = "run_created"
    RUN_STATUS_CHANGED = "run_status_changed"
    ROUTER_DECIDED = "router_decided"
    TASK_CREATED = "task_created"
    TASK_CLAIMED = "task_claimed"
    TASK_STARTED = "task_started"
    TOOL_CALLED = "tool_called"
    LLM_CALL_STARTED = "llm_call_started"
    LLM_CALL_COMPLETED = "llm_call_completed"
    PROVIDER_FALLBACK = "provider_fallback"
    CHECK_STARTED = "check_started"
    CHECK_COMPLETED = "check_completed"
    REVIEW_STARTED = "review_started"
    REVIEW_COMPLETED = "review_completed"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_BLOCKED = "task_blocked"
    DIFF_READY = "diff_ready"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"


async def append_event(
    session: AsyncSession,
    run_id: uuid.UUID,
    type: EventType,
    *,
    agent_id: str | None = None,
    task_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> AgentEvent:
    seq = (
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(last_event_seq=Run.last_event_seq + 1)
            .returning(Run.last_event_seq)
        )
    ).scalar_one()
    event = AgentEvent(
        run_id=run_id,
        seq=seq,
        type=type.value,
        agent_id=agent_id,
        task_id=task_id,
        payload=payload or {},
    )
    session.add(event)
    await session.flush()
    return event


async def list_events(
    session: AsyncSession, run_id: uuid.UUID, *, after_seq: int = 0, limit: int = 1000
) -> list[AgentEvent]:
    result = await session.scalars(
        select(AgentEvent)
        .where(AgentEvent.run_id == run_id, AgentEvent.seq > after_seq)
        .order_by(AgentEvent.seq)
        .limit(limit)
    )
    return list(result)
