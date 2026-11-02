"""The CrewAI crew A2A service: agent cards, auth, the worktree guard, and failure reporting."""

import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.a2a.client import CrewCallFailed, CrewServiceProcess, call_crew
from app.a2a.protocol import CrewRequest
from app.a2a.server import _checked_worktree, build_crew_app
from app.db.models import AgentEvent, Project, Run
from app.telemetry.hub import TelemetryHub


async def test_agent_cards_are_served_and_listed(app: FastAPI, client: httpx.AsyncClient) -> None:
    agents = (await client.get("/api/a2a/agents")).json()
    assert [(a["role"], a["reachable"]) for a in agents] == [("planner", True), ("coder", True)]
    coder = agents[1]["card"]
    assert coder["name"] == "coder_crew"
    assert coder["url"].endswith("/coder/")
    assert [s["id"] for s in coder["skills"]] == ["code"]


async def test_crew_service_requires_the_token(app: FastAPI) -> None:
    services = app.state.services
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_crew_app(services)), base_url="http://crew"
    ) as anonymous:
        response = await anonymous.get("/coder/.well-known/agent-card.json")
    assert response.status_code == 401


def test_crews_only_work_in_run_worktrees(tmp_path: Path) -> None:
    data = tmp_path / "data"
    run_tree = data / "worktrees" / "run-1"
    run_tree.mkdir(parents=True)
    assert _checked_worktree(run_tree, data) == run_tree.resolve()
    for outside in (tmp_path, data / "worktrees" / ".." / "elsewhere", data / "worktrees" / "nope"):
        with pytest.raises(PermissionError):
            _checked_worktree(outside, data)


async def test_a_failed_crew_task_is_reported_on_both_sides(app: FastAPI, tmp_path: Path) -> None:
    async with app.state.sessionmaker.begin() as session:
        project = Project(name="p", workspace_path=str(tmp_path))
        session.add(project)
        await session.flush()
        run = Run(project_id=project.id, title="r")
        session.add(run)
        await session.flush()
        run_id = run.id

    services = app.state.services
    request = CrewRequest(
        exchange_id=uuid.uuid4(),
        run_id=run_id,
        agent_id="coder_01",
        worktree=str(tmp_path),  # not a run worktree: the crew service refuses it
        workspace=str(tmp_path),
        expected_output="summary",
    )
    with pytest.raises(CrewCallFailed):
        await call_crew(
            "coder",
            hub=TelemetryHub(services, run_id),
            http=services.a2a_http,
            settings=services.settings,
            prompt="Implement it",
            request=request,
            parent="coder",
        )

    async with app.state.sessionmaker() as session:
        events = list(
            await session.scalars(
                select(AgentEvent)
                .where(AgentEvent.run_id == run_id, AgentEvent.type == "a2a_message")
                .order_by(AgentEvent.seq)
            )
        )
    states = [(e.payload["side"], e.payload["task_state"]) for e in events]
    assert states == [
        ("client", None),
        ("server", "submitted"),
        ("server", "working"),
        ("server", "failed"),
        ("client", "failed"),
    ]
    assert "not a run worktree" in events[3].payload["summary"]


class _FakeProcess:
    returncode = None

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float) -> None:
        return None


async def test_crew_service_process_is_not_started_twice(app: FastAPI) -> None:
    started: list[list[str]] = []

    def popen(args: list[str], **kwargs: object) -> _FakeProcess:
        started.append(args)
        return _FakeProcess()

    manager = CrewServiceProcess(app.state.settings, popen=popen)
    # The in-process crew app answers, so the service counts as already running.
    assert await manager.start(app.state.services.a2a_http) is True
    assert started == []
