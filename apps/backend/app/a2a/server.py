"""The CrewAI crew service: the Planner and Coder crews served as A2A agents (a2a-sdk 0.3).

Each crew is its own A2A agent with an Agent Card, mounted at `/planner` and `/coder`. A request
runs a single-agent crew exactly as the in-process version did (HexLLM through ProviderRouter,
MCP workspace tools on the run's worktree, TelemetryHub callbacks), and reports through the A2A
task lifecycle: submitted -> working -> completed (artifact) | failed.

The service writes to the same database as the backend, so its model calls, tool calls and
callbacks land in the run's event log. It accepts only bearer-authenticated requests and only
worktrees under the app's data directory.
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, Part, TaskState, TextPart
from a2a.utils import new_agent_text_message, new_task
from fastapi.concurrency import run_in_threadpool
from opentelemetry import propagate, trace
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount

from app import __version__
from app.a2a.protocol import METADATA_KEY, ROLES, CrewRequest, CrewRole, agent_name
from app.agents import roles
from app.agents.llm import HexLLM
from app.agents.mcp_bridge import McpWorkspace
from app.agents.tools import CODER, READ_ONLY, make_tools, tool_summary
from app.events.log import EventType
from app.orchestration.services import Services
from app.providers.router import CallContext
from app.telemetry.hub import TelemetryHub

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("hexmind.a2a")

SKILLS: dict[CrewRole, AgentSkill] = {
    "planner": AgentSkill(
        id="plan",
        name="Plan a code change",
        description="Break a developer request into small Blackboard tasks with acceptance "
        "criteria and target files (JSON). Reads the worktree with read-only MCP tools.",
        tags=["planning", "crewai"],
    ),
    "coder": AgentSkill(
        id="code",
        name="Implement a task",
        description="Edit files in the run's isolated worktree with MCP tools until the task's "
        "acceptance criteria and tests pass; returns a short summary.",
        tags=["coding", "crewai"],
    ),
}
PARENTS: dict[CrewRole, str] = {"planner": agent_name("planner"), "coder": agent_name("coder")}


def agent_card(role: CrewRole, base_url: str) -> AgentCard:
    return AgentCard(
        name=agent_name(role),
        description=f"CrewAI {role.title()} crew served over A2A by H.E.X Mind.",
        url=f"{base_url.rstrip('/')}/{role}/",
        version=__version__,
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[SKILLS[role]],
    )


class CrewExecutor(AgentExecutor):
    """Runs one crew per A2A request."""

    def __init__(self, services: Services, role: CrewRole) -> None:
        self.services = services
        self.role = role

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        assert context.message is not None
        task = context.current_task or new_task(context.message)
        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        metadata: dict[str, Any] = dict(context.metadata or {})
        request = CrewRequest.model_validate(metadata.get(METADATA_KEY) or {})
        hub = TelemetryHub(self.services, request.run_id, asyncio.get_running_loop())
        parent_ctx = propagate.extract(metadata)
        started = time.monotonic()
        with tracer.start_as_current_span(
            f"a2a.server {agent_name(self.role)}", context=parent_ctx
        ) as span:
            trace_id = format(span.get_span_context().trace_id, "032x")
            span.set_attributes(
                {
                    "hexmind.run_id": str(request.run_id),
                    "a2a.task_id": task.id,
                    "agent.framework": "crewai",
                }
            )

            async def note(direction: str, state: str, summary: str | None = None) -> None:
                await hub.record(
                    EventType.A2A_MESSAGE,
                    task_id=request.task_id,
                    agent_id=agent_name(self.role),
                    direction=direction,
                    side="server",
                    agent=agent_name(self.role),
                    peer="orchestrator",
                    exchange_id=str(request.exchange_id),
                    a2a_task_id=task.id,
                    context_id=task.context_id,
                    task_state=state,
                    trace_id=trace_id,
                    duration_ms=int((time.monotonic() - started) * 1000)
                    if state in ("completed", "failed")
                    else None,
                    summary=summary[:300] if summary else None,
                )

            await note("received", "submitted", context.get_user_input()[:200])
            await updater.update_status(TaskState.working)
            await note("sent", "working")
            try:
                result = await self._run_crew(request, context.get_user_input(), hub)
            except Exception as exc:
                logger.exception("crew %s failed for run %s", self.role, request.run_id)
                await updater.failed(
                    new_agent_text_message(f"{type(exc).__name__}: {exc}", task.context_id, task.id)
                )
                await note("sent", "failed", f"{type(exc).__name__}: {exc}")
                return
            await updater.add_artifact([Part(root=TextPart(text=result))], name="result")
            await updater.complete()
            await note("sent", "completed", result)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("crew runs cannot be cancelled mid-task")

    async def _run_crew(self, request: CrewRequest, prompt: str, hub: TelemetryHub) -> str:
        settings = self.services.settings
        worktree = _checked_worktree(Path(request.worktree), settings.data_dir)
        mcp = McpWorkspace(
            root=worktree,
            workspace=Path(request.workspace),
            allowed_images=settings.sandbox_images,
            check_timeout_s=settings.sandbox_timeout_s,
        )
        await run_in_threadpool(mcp.start)
        try:
            loop = asyncio.get_running_loop()
            llm = HexLLM(
                router=self.services.providers,
                loop=loop,
                ctx=CallContext(
                    run_id=request.run_id,
                    task_id=request.task_id,
                    agent_id=request.agent_id,
                    complexity=request.complexity,
                ),
                purpose=self.role,
                native_tools=settings.native_tool_calling,
            )

            def listener(name: str, args: dict[str, Any], ok: bool, text: str) -> None:
                hub.record_threadsafe(
                    EventType.TOOL_CALLED,
                    task_id=request.task_id,
                    agent_id=request.agent_id,
                    tool=name,
                    ok=ok,
                    summary=tool_summary(name, args, text),
                )

            factory = roles.planner if self.role == "planner" else roles.coder
            names = READ_ONLY if self.role == "planner" else CODER
            agent = factory(llm, make_tools(mcp, names, listener), settings.agent_max_iterations)
            return await roles.run_agent(
                agent,
                prompt,
                request.expected_output,
                hub.crew_callbacks(
                    request.agent_id, parent=PARENTS[self.role], task_id=request.task_id
                ),
            )
        finally:
            await run_in_threadpool(mcp.close)


def _checked_worktree(path: Path, data_dir: Path) -> Path:
    """Crews may only work in run worktrees the backend created."""
    root = (data_dir / "worktrees").resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        raise PermissionError(f"not a run worktree: {path}")
    return resolved


class _BearerAuth(BaseHTTPMiddleware):
    def __init__(self, app: Any, token: str) -> None:
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)


def build_crew_app(services: Services) -> Starlette:
    base_url = services.settings.crew_service_url
    mounts = []
    for role in ROLES:
        a2a = A2AStarletteApplication(
            agent_card=agent_card(role, base_url),
            http_handler=DefaultRequestHandler(
                agent_executor=CrewExecutor(services, role), task_store=InMemoryTaskStore()
            ),
        )
        mounts.append(Mount(f"/{role}", app=a2a.build()))
    app = Starlette(routes=mounts)
    app.add_middleware(_BearerAuth, token=services.settings.api_token)
    return app
