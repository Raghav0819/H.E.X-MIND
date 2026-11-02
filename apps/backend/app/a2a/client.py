"""The orchestrator side of A2A: calling CrewAI crews through ADK `RemoteA2aAgent`, and running
the crew service process in development.
"""

import asyncio
import logging
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from a2a.types import Part, TextPart
from google.adk.agents.remote_a2a_agent import A2A_METADATA_PREFIX, RemoteA2aAgent
from google.adk.events import Event

from app.a2a.protocol import (
    ROLES,
    CrewRequest,
    CrewRole,
    agent_name,
    card_path,
    current_trace_id,
    request_metadata,
)
from app.config import Settings
from app.events.log import EventType
from app.orchestration.adk import run_adk
from app.telemetry.hub import TelemetryHub

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]


class CrewCallFailed(RuntimeError):
    pass


def a2a_http_client(settings: Settings, **kwargs: Any) -> httpx.AsyncClient:
    """HTTP client for the crew service; tests pass an ASGI transport."""
    return httpx.AsyncClient(
        base_url=settings.crew_service_url,
        headers={"Authorization": f"Bearer {settings.api_token}"},
        timeout=settings.a2a_timeout_s,
        **kwargs,
    )


def remote_crew(
    role: CrewRole,
    *,
    settings: Settings,
    http: httpx.AsyncClient,
    request: CrewRequest,
    prompt: str,
) -> RemoteA2aAgent:
    """An ADK RemoteA2aAgent for one crew call. The message is exactly `prompt` (not the ADK
    session history); run/task/worktree and trace context go in the request metadata."""

    def context_builder(ctx: Any, name: str, converter: Any) -> tuple[list[Part], None]:
        return [Part(root=TextPart(text=prompt))], None

    return RemoteA2aAgent(
        name=agent_name(role),
        description=f"CrewAI {role} crew (A2A)",
        agent_card=f"{settings.crew_service_url.rstrip('/')}{card_path(role)}",
        httpx_client=http,
        timeout=settings.a2a_timeout_s,
        context_builder=context_builder,
        a2a_request_meta_provider=lambda ctx, message: request_metadata(request),
    )


async def call_crew(
    role: CrewRole,
    *,
    hub: TelemetryHub,
    http: httpx.AsyncClient,
    settings: Settings,
    prompt: str,
    request: CrewRequest,
    parent: str,
) -> str:
    """Send `prompt` to a crew over A2A and return its result text. Both ends of the exchange
    are recorded as `a2a_message` events joined by `exchange_id`."""
    name = agent_name(role)
    agent = remote_crew(role, settings=settings, http=http, request=request, prompt=prompt)
    hub.instrument(agent, task_id=request.task_id, parent=parent)

    async def note(direction: str, state: str | None, **extra: Any) -> None:
        await hub.record(
            EventType.A2A_MESSAGE,
            task_id=request.task_id,
            agent_id=name,
            direction=direction,
            side="client",
            agent="orchestrator",
            peer=name,
            exchange_id=str(request.exchange_id),
            task_state=state,
            **extra,
        )

    started = time.monotonic()
    await note("sent", None, trace_id=current_trace_id(), summary=prompt[:200])
    try:
        _, events = await run_adk(agent, message=prompt)
    except Exception as exc:
        await note("received", "failed", summary=f"{type(exc).__name__}: {exc}"[:300])
        raise CrewCallFailed(f"{name} A2A call failed: {exc}") from exc
    text, meta, error, state = _reply(events, name)
    duration = int((time.monotonic() - started) * 1000)
    if state == "completed" and not text:
        state, error = "failed", "empty reply"
    await note(
        "received",
        state,
        a2a_task_id=meta.get(A2A_METADATA_PREFIX + "task_id"),
        context_id=meta.get(A2A_METADATA_PREFIX + "context_id"),
        duration_ms=duration,
        summary=(error or text or "(empty reply)")[:300],
    )
    if state != "completed":
        raise CrewCallFailed(f"{name} A2A task {state}: {error or text or 'no result'}"[:500])
    return text


def _reply(events: list[Event], author: str) -> tuple[str, dict[str, Any], str | None, str]:
    """The remote agent's text, its A2A metadata, any error, and the A2A task's final state.
    A failed A2A task still comes back as an ordinary ADK event whose text is the failure
    message, so the state is read from the A2A response itself."""
    texts: list[str] = []
    meta: dict[str, Any] = {}
    error: str | None = None
    for event in events:
        if event.author != author:
            continue
        meta.update(event.custom_metadata or {})
        if event.error_message:
            error = event.error_message
        for part in (event.content.parts if event.content else None) or []:
            if part.text and not part.thought:
                texts.append(part.text)
    error = error or meta.get(A2A_METADATA_PREFIX + "error")
    response = meta.get(A2A_METADATA_PREFIX + "response")
    status = response.get("status") if isinstance(response, dict) else None
    state = str((status or {}).get("state") or ("failed" if error else "completed"))
    return "\n".join(texts).strip(), meta, error, state.removeprefix("TaskState.")


async def agent_cards(http: httpx.AsyncClient) -> list[dict[str, Any]]:
    """The crews' Agent Cards as served (for the A2A explorer)."""
    cards = []
    for role in ROLES:
        try:
            response = await http.get(card_path(role))
            response.raise_for_status()
            cards.append({"role": role, "reachable": True, "card": response.json()})
        except httpx.HTTPError as exc:
            cards.append({"role": role, "reachable": False, "error": str(exc), "card": None})
    return cards


class CrewServiceProcess:
    """Starts `python -m app.a2a` next to the backend in development (plan §11 runs it as its
    own Cloud Run service instead)."""

    def __init__(self, settings: Settings, popen: Callable[..., Any] = subprocess.Popen) -> None:
        self.settings = settings
        self._popen = popen
        self.process: Any = None

    async def start(self, http: httpx.AsyncClient, timeout_s: float = 60) -> bool:
        if await self._ready(http):
            logger.info("crew service already running at %s", self.settings.crew_service_url)
            return True
        self.process = self._popen([sys.executable, "-m", "app.a2a"], cwd=BACKEND_DIR)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                logger.error("crew service exited with code %s", self.process.returncode)
                return False
            if await self._ready(http):
                return True
            await asyncio.sleep(0.5)
        logger.error("crew service did not become ready in %ss", timeout_s)
        return False

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()

    async def _ready(self, http: httpx.AsyncClient) -> bool:
        try:
            return (await http.get(card_path("planner"), timeout=2)).status_code == 200
        except httpx.HTTPError:
            return False
