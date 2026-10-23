import asyncio
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.events.log import EventType, append_event, list_events


async def _create_run(client: httpx.AsyncClient, workspace: Path) -> dict:
    project = (await client.post("/api/projects", json={"workspace_path": str(workspace)})).json()
    response = await client.post("/api/runs", json={"project_id": project["id"], "title": "demo"})
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_run_persists_run_created_event(
    client: httpx.AsyncClient, workspace: Path
) -> None:
    run = await _create_run(client, workspace)
    assert run["status"] == "queued"
    assert run["last_event_seq"] == 1

    events = (await client.get(f"/api/runs/{run['id']}/events")).json()
    assert len(events) == 1
    event = events[0]
    assert event["schema_version"] == 1
    assert event["seq"] == 1
    assert event["type"] == "run_created"
    assert event["run_id"] == run["id"]
    assert event["payload"] == {"title": "demo"}
    uuid.UUID(event["event_id"])


async def test_concurrent_appends_get_unique_gap_free_seqs(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path
) -> None:
    run_id = uuid.UUID((await _create_run(client, workspace))["id"])
    sessionmaker = app.state.sessionmaker

    async def append(i: int) -> None:
        async with sessionmaker.begin() as session:
            await append_event(session, run_id, EventType.TOOL_CALLED, payload={"i": i})

    await asyncio.gather(*(append(i) for i in range(25)))

    async with sessionmaker() as session:
        seqs = [e.seq for e in await list_events(session, run_id)]
    assert seqs == list(range(1, 27))


async def test_rolled_back_event_does_not_consume_seq(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path
) -> None:
    run_id = uuid.UUID((await _create_run(client, workspace))["id"])
    sessionmaker = app.state.sessionmaker

    with pytest.raises(RuntimeError):
        async with sessionmaker.begin() as session:
            await append_event(session, run_id, EventType.TOOL_CALLED)
            raise RuntimeError("abort transaction")

    async with sessionmaker.begin() as session:
        event = await append_event(session, run_id, EventType.TOOL_CALLED)
    assert event.seq == 2


async def test_events_after_seq(client: httpx.AsyncClient, app: FastAPI, workspace: Path) -> None:
    run = await _create_run(client, workspace)
    async with app.state.sessionmaker.begin() as session:
        for _ in range(3):
            await append_event(session, uuid.UUID(run["id"]), EventType.TOOL_CALLED)

    events = (await client.get(f"/api/runs/{run['id']}/events", params={"after_seq": 2})).json()
    assert [e["seq"] for e in events] == [3, 4]


async def test_run_endpoints_404(client: httpx.AsyncClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/api/runs/{missing}")).status_code == 404
    assert (await client.get(f"/api/runs/{missing}/events")).status_code == 404
    create = await client.post("/api/runs", json={"project_id": missing, "title": "x"})
    assert create.status_code == 404
