"""TelemetryHub: one sink for every framework callback (plan §7.1, criterion 5).

ADK: all eight agent-level callbacks are attached to every agent of a tree by `instrument`
(before/after agent, before/after model, on_model_error, before/after tool, on_tool_error).
CrewAI: `crew_callbacks` returns the crew's step/task callbacks and before/after kickoff hooks.

Each callback becomes (1) a run event (`agent_started`, `agent_finished`, `callback_fired`,
`schema_validated`) and (2) attributes on the current OpenTelemetry span, so the UI's callback
stream, agent grid and schema checks are fed by the callbacks themselves. Telemetry never
changes agent behaviour: every hub callback returns None, runs first in its callback list, and
swallows its own failures.
"""

import asyncio
import contextlib
import logging
import threading
import time
import uuid
from collections.abc import Callable, Coroutine, Iterator
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents import BaseAgent, LlmAgent, LoopAgent, ParallelAgent, SequentialAgent
from opentelemetry import trace

from app.events.log import EventType, append_event
from app.orchestration.adk import SCHEMA_CHECK_KEY
from app.orchestration.services import Services

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("hexmind")

MAX_DETAIL = 300

ADK_HOOKS = (
    "before_agent_callback",
    "after_agent_callback",
    "before_model_callback",
    "after_model_callback",
    "on_model_error_callback",
    "before_tool_callback",
    "after_tool_callback",
    "on_tool_error_callback",
)


def agent_kind(agent: BaseAgent) -> str:
    for cls, kind in (
        (LlmAgent, "llm"),
        (SequentialAgent, "sequential"),
        (LoopAgent, "loop"),
        (ParallelAgent, "parallel"),
    ):
        if isinstance(agent, cls):
            return kind
    return "custom"


def _clip(text: Any) -> str:
    text = str(text)
    return text if len(text) <= MAX_DETAIL else text[: MAX_DETAIL - 1] + "…"


@dataclass
class TelemetryHub:
    services: Services
    run_id: uuid.UUID
    loop: asyncio.AbstractEventLoop = field(default_factory=asyncio.get_running_loop)
    _started: dict[tuple[str, str], list[float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ---------- recording ----------

    async def record(
        self,
        type: EventType,
        *,
        task_id: uuid.UUID | None = None,
        agent_id: str | None = None,
        **payload: Any,
    ) -> None:
        try:
            async with self.services.sessionmaker.begin() as session:
                await append_event(
                    session, self.run_id, type, task_id=task_id, agent_id=agent_id, payload=payload
                )
        except Exception:  # monitoring must never take a run down
            logger.exception("telemetry: failed to record %s for run %s", type, self.run_id)

    def record_threadsafe(self, type: EventType, **kwargs: Any) -> None:
        """For callbacks that run on a worker thread (CrewAI runs crews in a thread)."""
        self._submit(self.record(type, **kwargs))

    def _submit(self, coro: Coroutine[Any, Any, None]) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:  # already on the server loop: do not block it
            self.loop.create_task(coro)
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=30)
        except Exception:
            logger.exception("telemetry: threadsafe record failed for run %s", self.run_id)

    def _start(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._started.setdefault(key, []).append(time.monotonic())

    def _elapsed_ms(self, key: tuple[str, str]) -> int | None:
        with self._lock:
            stack = self._started.get(key)
            if not stack:
                return None
            return int((time.monotonic() - stack.pop()) * 1000)

    def _span(self, **attributes: Any) -> None:
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attributes(
                {
                    "hexmind.run_id": str(self.run_id),
                    **{k: v for k, v in attributes.items() if v is not None},
                }
            )

    # ---------- ADK ----------

    def instrument(
        self, agent: BaseAgent, *, task_id: uuid.UUID | None = None, parent: str | None = None
    ) -> BaseAgent:
        """Attach the hub's callbacks to every agent in the tree, ahead of existing ones.
        `parent` names the agent this tree runs under when it is a separate ADK invocation
        (a task's reflection loop runs under the run's `execute` step)."""
        callbacks = self._adk_callbacks(agent, task_id, parent)
        for hook, callback in callbacks.items():
            if hook not in type(agent).model_fields:
                continue  # model/tool hooks exist only on LlmAgent
            existing = getattr(agent, hook)
            existing = existing if isinstance(existing, list) else [existing] if existing else []
            setattr(agent, hook, [callback, *existing])
        for sub in agent.sub_agents:
            self.instrument(sub, task_id=task_id)
        return agent

    def _adk_callbacks(
        self, agent: BaseAgent, task_id: uuid.UUID | None, root_parent: str | None
    ) -> dict[str, Callable[..., Any]]:
        name, kind = agent.name, agent_kind(agent)
        parent = agent.parent_agent.name if agent.parent_agent else root_parent
        schema = getattr(agent, "output_schema", None)
        schema_name = getattr(schema, "__name__", None)

        def fired(hook: str, detail: str | None = None) -> Coroutine[Any, Any, None]:
            return self.record(
                EventType.CALLBACK_FIRED,
                task_id=task_id,
                agent_id=name,
                framework="adk",
                hook=hook,
                agent=name,
                detail=_clip(detail) if detail else None,
            )

        async def before_agent(callback_context: Any) -> None:
            self._start((callback_context.invocation_id, name))
            if schema_name:
                callback_context.state[SCHEMA_CHECK_KEY] = None
            self._span(**{"agent.name": name, "agent.framework": "adk", "agent.kind": kind})
            await self.record(
                EventType.AGENT_STARTED,
                task_id=task_id,
                agent_id=name,
                agent=name,
                framework="adk",
                kind=kind,
                parent=parent,
            )

        async def after_agent(callback_context: Any) -> None:
            await self.record(
                EventType.AGENT_FINISHED,
                task_id=task_id,
                agent_id=name,
                agent=name,
                framework="adk",
                ok=True,
                duration_ms=self._elapsed_ms((callback_context.invocation_id, name)),
            )
            check = callback_context.state.get(SCHEMA_CHECK_KEY) if schema_name else None
            if check and check.get("agent") == name:
                self._span(**{"schema.name": schema_name, "schema.status": check["status"]})
                await self.record(
                    EventType.SCHEMA_VALIDATED,
                    task_id=task_id,
                    agent_id=name,
                    agent=name,
                    schema_name=schema_name,
                    status=check["status"],
                    errors=[_clip(e) for e in check.get("errors", [])],
                )

        async def before_model(callback_context: Any, llm_request: Any) -> None:
            messages = len(llm_request.contents or [])
            tools = len(getattr(llm_request, "tools_dict", {}) or {})
            await fired("before_model_callback", f"{messages} message(s), {tools} tool(s)")

        async def after_model(callback_context: Any, llm_response: Any) -> None:
            meta = llm_response.custom_metadata or {}
            usage = llm_response.usage_metadata
            self._span(
                **{
                    "llm.provider": meta.get("provider"),
                    "llm.model": meta.get("model"),
                    "llm.latency_ms": meta.get("latency_ms"),
                    "llm.input_tokens": usage.prompt_token_count if usage else None,
                    "llm.output_tokens": usage.candidates_token_count if usage else None,
                    "cost.usd": meta.get("est_cost_usd"),
                }
            )
            calls = [
                p.function_call.name
                for p in (llm_response.content.parts if llm_response.content else None) or []
                if p.function_call
            ]
            detail = f"{meta.get('provider', '?')}/{meta.get('model', '?')}"
            if usage:
                detail += f", {usage.prompt_token_count}→{usage.candidates_token_count} tokens"
            if calls:
                detail += f", calls {', '.join(calls)}"
            await fired("after_model_callback", detail)

        async def on_model_error(callback_context: Any, llm_request: Any, error: Exception) -> None:
            self._span(**{"error.type": type(error).__name__})
            await fired("on_model_error_callback", f"{type(error).__name__}: {error}")

        async def before_tool(tool: Any, args: dict[str, Any], tool_context: Any) -> None:
            self._span(**{"tool.name": tool.name})
            await fired("before_tool_callback", f"{tool.name}({', '.join(sorted(args))})")

        async def after_tool(
            tool: Any, args: dict[str, Any], tool_context: Any, tool_response: Any
        ) -> None:
            await fired("after_tool_callback", f"{tool.name} → {_clip(tool_response)}")

        async def on_tool_error(
            tool: Any, args: dict[str, Any], tool_context: Any, error: Exception
        ) -> None:
            await fired("on_tool_error_callback", f"{tool.name}: {type(error).__name__}: {error}")

        return dict(
            zip(
                ADK_HOOKS,
                (
                    before_agent,
                    after_agent,
                    before_model,
                    after_model,
                    on_model_error,
                    before_tool,
                    after_tool,
                    on_tool_error,
                ),
                strict=True,
            )
        )

    # ---------- CrewAI ----------

    def crew_callbacks(
        self, agent_id: str, *, parent: str, task_id: uuid.UUID | None = None
    ) -> "CrewCallbacks":
        """`parent` is the ADK agent the crew runs inside (e.g. `plan` or `coder`)."""
        return CrewCallbacks(self, agent_id, parent, task_id)

    @contextlib.contextmanager
    def crew_span(self, agent_id: str) -> Iterator[None]:
        with tracer.start_as_current_span(f"crewai.crew {agent_id}") as span:
            span.set_attributes(
                {
                    "hexmind.run_id": str(self.run_id),
                    "agent.name": agent_id,
                    "agent.framework": "crewai",
                    "agent.kind": "crew",
                }
            )
            yield


@dataclass
class CrewCallbacks:
    """CrewAI hooks for a single-agent crew. They run on the crew's worker thread."""

    hub: TelemetryHub
    agent_id: str
    parent: str
    task_id: uuid.UUID | None
    _started: float = 0.0

    def _fired(self, hook: str, detail: str | None) -> None:
        self.hub.record_threadsafe(
            EventType.CALLBACK_FIRED,
            task_id=self.task_id,
            agent_id=self.agent_id,
            framework="crewai",
            hook=hook,
            agent=self.agent_id,
            detail=_clip(detail) if detail else None,
        )

    def before_kickoff(self, inputs: dict[str, Any] | None) -> dict[str, Any] | None:
        self._started = time.monotonic()
        self.hub.record_threadsafe(
            EventType.AGENT_STARTED,
            task_id=self.task_id,
            agent_id=self.agent_id,
            agent=self.agent_id,
            framework="crewai",
            kind="crew",
            parent=self.parent,
        )
        return inputs

    def after_kickoff(self, output: Any) -> Any:
        self.hub.record_threadsafe(
            EventType.AGENT_FINISHED,
            task_id=self.task_id,
            agent_id=self.agent_id,
            agent=self.agent_id,
            framework="crewai",
            ok=True,
            duration_ms=int((time.monotonic() - self._started) * 1000) if self._started else None,
        )
        return output

    def span(self) -> contextlib.AbstractContextManager[None]:
        return self.hub.crew_span(self.agent_id)

    def step_callback(self, step: Any) -> None:
        self._fired("step_callback", describe_step(step))

    def task_callback(self, output: Any) -> None:
        raw = getattr(output, "raw", None) or str(output)
        self._fired("task_callback", f"task done: {raw}")


def describe_step(step: Any) -> str:
    """CrewAI passes AgentAction (a tool use), ToolResult or AgentFinish objects."""
    kind = type(step).__name__
    tool = getattr(step, "tool", None)
    if tool:
        return f"{kind}: {tool}"
    for attr in ("output", "result", "text"):
        value = getattr(step, attr, None)
        if value:
            return f"{kind}: {value}"
    return kind
