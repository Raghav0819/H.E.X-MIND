import asyncio
import uuid
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import select, update

from app.blackboard import store
from app.db.models import AgentEvent, Project, Run, Task


@pytest.fixture
async def run_id(app: FastAPI, workspace: Path) -> uuid.UUID:
    async with app.state.sessionmaker.begin() as session:
        project = Project(name="p", workspace_path=str(workspace))
        session.add(project)
        await session.flush()
        run = Run(project_id=project.id, title="r")
        session.add(run)
        await session.flush()
        return run.id


async def _add(app: FastAPI, run_id: uuid.UUID, title: str, **kwargs) -> uuid.UUID:
    async with app.state.sessionmaker.begin() as session:
        task = await store.add_task(session, run_id, title=title, description="d", **kwargs)
        return task.id


async def _claim(app: FastAPI, run_id: uuid.UUID, worker: str, **kwargs) -> Task | None:
    async with app.state.sessionmaker.begin() as session:
        return await store.claim_next(session, run_id, worker, **kwargs)


async def _move(app: FastAPI, task_id: uuid.UUID, *statuses: str) -> None:
    for status in statuses:
        async with app.state.sessionmaker.begin() as session:
            await store.transition(session, task_id, status)


async def test_concurrent_workers_never_double_claim(app: FastAPI, run_id: uuid.UUID) -> None:
    for i in range(50):
        await _add(app, run_id, f"task {i}")
    claims: list[uuid.UUID] = []

    async def worker(name: str) -> None:
        while True:
            task = await _claim(app, run_id, name)
            if task is None:
                return
            claims.append(task.id)
            await asyncio.sleep(0)  # let other workers interleave
            await _move(app, task.id, "running", "completed")

    await asyncio.gather(*(worker(f"w{i}") for i in range(10)))

    assert len(claims) == 50
    assert max(Counter(claims).values()) == 1
    async with app.state.sessionmaker() as session:
        statuses = Counter(await session.scalars(select(Task.status)))
        claimed_events = await session.scalars(
            select(AgentEvent).where(AgentEvent.type == "task_claimed")
        )
        assert statuses == {"completed": 50}
        assert len(list(claimed_events)) == 50


async def test_add_task_rejects_duplicates_and_emits_event(app: FastAPI, run_id: uuid.UUID) -> None:
    await _add(app, run_id, "Add delete button", target_files=["b.ts", "a.ts", "a.ts"])
    with pytest.raises(store.DuplicateTask):
        await _add(app, run_id, "  add DELETE button. ")
    async with app.state.sessionmaker() as session:
        task = await session.scalar(select(Task))
        event = await session.scalar(select(AgentEvent).where(AgentEvent.type == "task_created"))
    assert task is not None and task.target_files == ["a.ts", "b.ts"]
    assert event is not None and event.payload["target_files"] == ["a.ts", "b.ts"]


async def test_dependencies_gate_claims(app: FastAPI, run_id: uuid.UUID) -> None:
    first = await _add(app, run_id, "model")
    await _add(app, run_id, "ui", depends_on=[first], priority=10)

    claimed = await _claim(app, run_id, "w1")
    assert claimed is not None and claimed.id == first  # higher priority but blocked by dep
    assert await _claim(app, run_id, "w2") is None

    await _move(app, first, "running", "completed")
    second = await _claim(app, run_id, "w2")
    assert second is not None and second.title == "ui"


async def test_overlapping_files_are_not_worked_on_in_parallel(
    app: FastAPI, run_id: uuid.UUID
) -> None:
    a = await _add(app, run_id, "a", target_files=["src/app.ts", "src/a.ts"])
    await _add(app, run_id, "b", target_files=["src/app.ts"])
    c = await _add(app, run_id, "c", target_files=["src/c.ts"])

    assert (await _claim(app, run_id, "w1")).id == a  # type: ignore[union-attr]
    assert (await _claim(app, run_id, "w2")).id == c  # type: ignore[union-attr]  b overlaps a
    assert await _claim(app, run_id, "w3") is None

    await _move(app, a, "running", "completed")
    assert (await _claim(app, run_id, "w3")).title == "b"  # type: ignore[union-attr]


async def test_failure_blocks_dependents(app: FastAPI, run_id: uuid.UUID) -> None:
    base = await _add(app, run_id, "base")
    child = await _add(app, run_id, "child", depends_on=[base])
    await _claim(app, run_id, "w1")
    await _move(app, base, "running", "failed")
    async with app.state.sessionmaker() as session:
        assert (await session.get(Task, child)).status == "blocked"  # type: ignore[union-attr]
        blocked = await session.scalar(select(AgentEvent).where(AgentEvent.type == "task_blocked"))
    assert blocked is not None and "base" in blocked.payload["reason"]


async def test_invalid_transitions_are_rejected(app: FastAPI, run_id: uuid.UUID) -> None:
    task_id = await _add(app, run_id, "t")
    with pytest.raises(store.InvalidTransition):
        await _move(app, task_id, "completed")


async def test_request_changes_retries_then_blocks(app: FastAPI, run_id: uuid.UUID) -> None:
    task_id = await _add(app, run_id, "t", max_attempts=2)
    for attempt in (1, 2):
        task = await _claim(app, run_id, "w1")
        assert task is not None and task.attempts == attempt
        await _move(app, task_id, "running", "review")
        async with app.state.sessionmaker.begin() as session:
            task = await store.request_changes(session, task_id, f"fix {attempt}")
    async with app.state.sessionmaker() as session:
        task = await session.get(Task, task_id)
    assert task is not None and task.status == "blocked"
    assert "fix 1" in task.description


async def test_expired_leases_are_reaped(app: FastAPI, run_id: uuid.UUID) -> None:
    task_id = await _add(app, run_id, "t", max_attempts=2)
    await _claim(app, run_id, "w1", lease=timedelta(seconds=-1))  # already expired
    async with app.state.sessionmaker.begin() as session:
        reaped = await store.reap_expired_leases(session, run_id)
    assert [t.id for t in reaped] == [task_id]
    retry = await _claim(app, run_id, "w2")
    assert retry is not None and retry.id == task_id and retry.attempts == 2

    async with app.state.sessionmaker.begin() as session:
        await session.execute(
            update(Task).where(Task.id == task_id).values(lease_expires_at=Task.created_at)
        )
        await store.reap_expired_leases(session, run_id)
    async with app.state.sessionmaker() as session:
        assert (await session.get(Task, task_id)).status == "blocked"  # type: ignore[union-attr]


async def test_claim_specific_task_once(app: FastAPI, run_id: uuid.UUID) -> None:
    task_id = await _add(app, run_id, "t")

    async def claim(worker: str) -> Task | None:
        async with app.state.sessionmaker.begin() as session:
            return await store.claim_task(session, task_id, worker)

    results = await asyncio.gather(*(claim(f"w{i}") for i in range(8)))
    assert sum(r is not None for r in results) == 1


async def test_tasks_api_lifecycle(app: FastAPI, client, run_id: uuid.UUID) -> None:
    created = await client.post(
        "/api/tasks",
        json={
            "run_id": str(run_id),
            "title": "Add filter",
            "description": "d",
            "target_files": ["a.ts"],
        },
    )
    assert created.status_code == 201
    task_id = created.json()["id"]
    dup = await client.post(
        "/api/tasks", json={"run_id": str(run_id), "title": "add filter", "description": "d"}
    )
    assert dup.status_code == 409

    claim = await client.post(f"/api/tasks/{task_id}/claim", json={"worker": "w1"})
    assert claim.status_code == 200 and claim.json()["status"] == "claimed"
    again = await client.post(f"/api/tasks/{task_id}/claim", json={"worker": "w2"})
    assert again.status_code == 409

    early = await client.post(f"/api/tasks/{task_id}/review", json={"verdict": "approved"})
    assert early.status_code == 409  # not in review yet
    await _move(app, uuid.UUID(task_id), "running", "review")
    reviewed = await client.post(
        f"/api/tasks/{task_id}/review",
        json={
            "verdict": "changes_requested",
            "findings": [{"file": "a.ts", "line": 3, "message": "off by one"}],
        },
    )
    assert reviewed.status_code == 200 and reviewed.json()["status"] == "pending"
    assert "off by one" in reviewed.json()["description"]

    listed = (await client.get("/api/tasks", params={"run_id": str(run_id)})).json()
    assert [t["title"] for t in listed] == ["Add filter"]


async def test_only_the_lease_holder_can_renew(app: FastAPI, run_id: uuid.UUID) -> None:
    task_id = await _add(app, run_id, "t")
    await _claim(app, run_id, "w1", lease=timedelta(seconds=-1))

    async def renew(worker: str) -> bool:
        async with app.state.sessionmaker.begin() as session:
            return await store.renew_lease(session, task_id, worker)

    assert await renew("w2") is False
    assert await renew("w1") is True  # still holds it: renewing rescues the expired lease
    async with app.state.sessionmaker.begin() as session:
        assert await store.reap_expired_leases(session, run_id) == []

    async with app.state.sessionmaker.begin() as session:
        await session.execute(
            update(Task).where(Task.id == task_id).values(lease_expires_at=Task.created_at)
        )
        await store.reap_expired_leases(session, run_id)
    assert await renew("w1") is False  # reaped: the lease is gone
