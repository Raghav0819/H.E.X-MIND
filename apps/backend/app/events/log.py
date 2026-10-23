"""Append-only per-run event log (plan §4.1).

`seq` is per-run and gap-free: it is taken from `runs.last_event_seq` with an UPDATE ... RETURNING
in the caller's transaction, which row-locks the run until commit, so concurrent writers to the
same run are serialized and a rolled-back event does not consume a number.
"""

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentEvent, Run
from app.events.schema import PAYLOADS, EventType

__all__ = ["EventType", "append_event", "list_events"]


async def append_event(
    session: AsyncSession,
    run_id: uuid.UUID,
    type: EventType,
    *,
    agent_id: str | None = None,
    task_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> AgentEvent:
    # Validate against the event contract before taking a sequence number.
    validated = PAYLOADS[type].model_validate(payload or {}).model_dump(mode="json")
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
        payload=validated,
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
