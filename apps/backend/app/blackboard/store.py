"""Blackboard (plan §3.3, §4.4): PostgreSQL-backed shared task state for the worker swarm.

Lifecycle:
    pending -> claimed -> running -> review -> completed
    running/review -> changes_requested -> pending (retry)        attempts < max_attempts
    any open state -> failed | blocked                             (dependents become blocked)

Claims are atomic. `claim_next` locks the run row (serializing claimers of the same run, which
the file-disjointness check needs) and selects with FOR UPDATE SKIP LOCKED. Expired leases are
returned to `pending` by `reap_expired_leases`.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, Task, TaskDependency
from app.events.log import EventType, append_event

OPEN_STATUSES = ("pending", "claimed", "running", "review", "changes_requested")
TERMINAL_STATUSES = ("completed", "failed", "blocked", "cancelled")

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"claimed", "blocked", "cancelled"},
    "claimed": {"running", "pending", "failed", "blocked", "cancelled"},
    "running": {"review", "completed", "failed", "changes_requested", "pending", "cancelled"},
    "review": {"completed", "changes_requested", "failed", "blocked", "cancelled"},
    "changes_requested": {"running", "pending", "blocked", "failed", "cancelled"},
}

DEFAULT_LEASE = timedelta(minutes=10)


class DuplicateTask(ValueError):
    pass


class InvalidTransition(ValueError):
    pass


def normalize_title(title: str) -> str:
    return " ".join(title.lower().split()).strip(" .")


async def add_task(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    title: str,
    description: str,
    acceptance_criteria: list[str] | None = None,
    target_files: list[str] | None = None,
    depends_on: list[uuid.UUID] | None = None,
    priority: int = 0,
    complexity: str | None = None,
    max_attempts: int = 3,
) -> Task:
    """Add a task to the run's Blackboard. Rejects near-duplicate titles within the run."""
    existing = await session.scalars(select(Task.title).where(Task.run_id == run_id))
    if normalize_title(title) in {normalize_title(t) for t in existing}:
        raise DuplicateTask(f"a task titled '{title}' already exists in this run")

    task = Task(
        run_id=run_id,
        title=title,
        description=description,
        acceptance_criteria=acceptance_criteria or [],
        target_files=sorted(set(target_files or [])),
        priority=priority,
        complexity=complexity,
        max_attempts=max_attempts,
    )
    session.add(task)
    await session.flush()
    for dependency in depends_on or []:
        session.add(TaskDependency(task_id=task.id, depends_on=dependency))
    await session.flush()
    await append_event(
        session,
        run_id,
        EventType.TASK_CREATED,
        agent_id="planner",
        task_id=task.id,
        payload={
            "title": title,
            "complexity": complexity,
            "depends_on": [str(d) for d in depends_on or []],
            "target_files": task.target_files,
        },
    )
    return task


_CLAIM_NEXT = text(
    """
    UPDATE tasks SET status = 'claimed', claimed_by = :worker, claimed_at = now(),
           lease_expires_at = now() + make_interval(secs => :lease_s),
           attempts = attempts + 1, updated_at = clock_timestamp()
    WHERE id = (
        SELECT t.id FROM tasks t
        WHERE t.run_id = :run_id AND t.status = 'pending'
          AND NOT EXISTS (
              SELECT 1 FROM task_dependencies d JOIN tasks p ON p.id = d.depends_on
              WHERE d.task_id = t.id AND p.status <> 'completed')
          AND NOT EXISTS (
              SELECT 1 FROM tasks o
              WHERE o.run_id = t.run_id AND o.id <> t.id
                AND o.status IN ('claimed', 'running', 'review', 'changes_requested')
                AND o.target_files ?| ARRAY(SELECT jsonb_array_elements_text(t.target_files)))
        ORDER BY t.priority DESC, t.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1)
    RETURNING id
    """
)


async def claim_next(
    session: AsyncSession, run_id: uuid.UUID, worker: str, *, lease: timedelta = DEFAULT_LEASE
) -> Task | None:
    """Atomically claim the next runnable task: pending, dependencies completed, and no
    overlapping target files with a task another worker holds."""
    # Serialize claimers of this run so two workers can't both pass the overlap check.
    await session.execute(select(Run.id).where(Run.id == run_id).with_for_update())
    task_id = (
        await session.execute(
            _CLAIM_NEXT, {"run_id": run_id, "worker": worker, "lease_s": lease.total_seconds()}
        )
    ).scalar_one_or_none()
    if task_id is None:
        return None
    task = await session.get(Task, task_id, populate_existing=True)
    assert task is not None
    await append_event(
        session,
        run_id,
        EventType.TASK_CLAIMED,
        agent_id=worker,
        task_id=task.id,
        payload={"worker": worker},
    )
    return task


async def claim_task(
    session: AsyncSession, task_id: uuid.UUID, worker: str, *, lease: timedelta = DEFAULT_LEASE
) -> Task | None:
    """Atomically claim one specific pending task; None if it is not claimable."""
    task = await session.get(Task, task_id)
    if task is None:
        return None
    await session.execute(select(Run.id).where(Run.id == task.run_id).with_for_update())
    claimed = (
        await session.execute(
            update(Task)
            .where(Task.id == task_id, Task.status == "pending")
            .values(
                status="claimed",
                claimed_by=worker,
                claimed_at=func.now(),
                lease_expires_at=func.now() + lease,
                attempts=Task.attempts + 1,
            )
            .returning(Task.id)
        )
    ).scalar_one_or_none()
    if claimed is None:
        return None
    await session.refresh(task)
    await append_event(
        session,
        task.run_id,
        EventType.TASK_CLAIMED,
        agent_id=worker,
        task_id=task.id,
        payload={"worker": worker},
    )
    return task


async def transition(
    session: AsyncSession, task_id: uuid.UUID, to: str, *, worker: str | None = None
) -> Task:
    """Move a task to a new status, enforcing the lifecycle."""
    task = await session.scalar(select(Task).where(Task.id == task_id).with_for_update())
    if task is None:
        raise LookupError("task not found")
    if to not in ALLOWED_TRANSITIONS.get(task.status, set()):
        raise InvalidTransition(f"{task.status} -> {to}")
    task.status = to
    if to in ("running", "review"):
        task.lease_expires_at = datetime.now(UTC) + DEFAULT_LEASE
    if to == "pending":
        task.claimed_by = None
        task.lease_expires_at = None
    await session.flush()
    if to in ("failed", "blocked"):
        await _block_dependents(session, task)
    return task


async def request_changes(session: AsyncSession, task_id: uuid.UUID, findings: str) -> Task:
    """Send a reviewed task back for another attempt, or block it when attempts are used up."""
    task = await session.scalar(select(Task).where(Task.id == task_id).with_for_update())
    if task is None:
        raise LookupError("task not found")
    if task.attempts >= task.max_attempts:
        await transition(session, task_id, "blocked")
        await append_event(
            session,
            task.run_id,
            EventType.TASK_BLOCKED,
            task_id=task.id,
            payload={"reason": f"review requested changes after {task.attempts} attempts"},
        )
        return task
    task.description = f"{task.description}\n\nReviewer findings to address:\n{findings}"
    await transition(session, task_id, "changes_requested")
    return await transition(session, task_id, "pending")


async def _block_dependents(session: AsyncSession, task: Task) -> None:
    dependents = list(
        await session.scalars(
            select(Task)
            .join(TaskDependency, TaskDependency.task_id == Task.id)
            .where(TaskDependency.depends_on == task.id, Task.status.in_(OPEN_STATUSES))
        )
    )
    for dependent in dependents:
        await transition(session, dependent.id, "blocked")
        await append_event(
            session,
            dependent.run_id,
            EventType.TASK_BLOCKED,
            task_id=dependent.id,
            payload={"reason": f"dependency '{task.title}' {task.status}"},
        )


async def reap_expired_leases(session: AsyncSession, run_id: uuid.UUID) -> list[Task]:
    """Return tasks whose worker lease expired to `pending`, or block them when out of attempts."""
    expired = list(
        await session.scalars(
            select(Task)
            .where(
                Task.run_id == run_id,
                Task.status.in_(("claimed", "running", "review")),
                Task.lease_expires_at < func.now(),
            )
            .with_for_update(skip_locked=True)
        )
    )
    for task in expired:
        if task.attempts >= task.max_attempts:
            task.status = "blocked"
            await session.flush()
            await _block_dependents(session, task)
            await append_event(
                session,
                run_id,
                EventType.TASK_BLOCKED,
                task_id=task.id,
                payload={"reason": "worker lease expired and attempts are used up"},
            )
        else:
            task.status = "pending"
            task.claimed_by = None
            task.lease_expires_at = None
    await session.flush()
    return expired


async def renew_lease(
    session: AsyncSession, task_id: uuid.UUID, worker: str, *, lease: timedelta = DEFAULT_LEASE
) -> bool:
    """Extend a worker's lease on a task it still holds. False means the lease was lost (it
    expired and the task was reaped or reclaimed), so the worker must stop working on it."""
    renewed = await session.execute(
        update(Task)
        .where(
            Task.id == task_id,
            Task.claimed_by == worker,
            Task.status.in_(("claimed", "running", "review", "changes_requested")),
        )
        .values(lease_expires_at=func.now() + lease)
        .returning(Task.id)
    )
    return renewed.scalar_one_or_none() is not None


async def run_has_open_tasks(session: AsyncSession, run_id: uuid.UUID) -> bool:
    count = await session.scalar(
        select(func.count()).where(Task.run_id == run_id, Task.status.in_(OPEN_STATUSES))
    )
    return bool(count)
