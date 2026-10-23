import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.events import export_schema
from app.events.log import EventType, append_event
from app.events.schema import PAYLOADS

GENERATED = (
    Path(__file__).resolve().parents[2] / "desktop/src/renderer/src/generated/events.schema.json"
)


def test_every_event_type_has_a_payload_model() -> None:
    assert set(PAYLOADS) == set(EventType)


def test_committed_schema_matches_backend_models() -> None:
    """The renderer's types are generated from this file; regenerate with `npm run gen:events`."""
    assert GENERATED.read_text(encoding="utf-8") == export_schema.render()


async def test_append_event_rejects_invalid_payloads(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path
) -> None:
    project = (await client.post("/api/projects", json={"workspace_path": str(workspace)})).json()
    run = (await client.post("/api/runs", json={"project_id": project["id"], "title": "t"})).json()

    for payload in ({}, {"tool": "x", "unexpected": 1}, {"tool": 3}):
        with pytest.raises(ValidationError):
            async with app.state.sessionmaker.begin() as session:
                await append_event(
                    session, uuid.UUID(run["id"]), EventType.TOOL_CALLED, payload=payload
                )

    # Rejected events did not consume sequence numbers.
    assert (await client.get(f"/api/runs/{run['id']}")).json()["last_event_seq"] == 1
