"""TelemetryHub: every ADK callback type and the CrewAI hooks become run events and spans."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools import FunctionTool
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel
from sqlalchemy import select

from app.agents.adk_llm import HexAdkLlm
from app.db.models import AgentEvent, Project, Run
from app.orchestration.adk import model_error_fallback, run_adk, schema_guard
from app.providers.base import Completion, LLMRequest, ProviderError, ToolCall
from app.providers.router import CallContext
from app.telemetry.hub import ADK_HOOKS, TelemetryHub, describe_step
from app.telemetry.tracing import add_span_processor
from tests.conftest import ScriptedAdapter, use_adapter


class Verdict(BaseModel):
    ok: bool


def lookup(key: str) -> dict:
    """Look up a value."""
    return {"value": key.upper()}


def explode(key: str) -> dict:
    """Always fails."""
    raise RuntimeError("tool broke")


@pytest.fixture
def spans() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


async def _run(app: FastAPI) -> uuid.UUID:
    async with app.state.sessionmaker.begin() as session:
        project = Project(name="p", workspace_path="/tmp/p")
        session.add(project)
        await session.flush()
        run = Run(project_id=project.id, title="r")
        session.add(run)
        await session.flush()
        return run.id


async def _events(app: FastAPI, run_id: uuid.UUID) -> list[AgentEvent]:
    async with app.state.sessionmaker() as session:
        return list(
            await session.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.seq)
            )
        )


def _llm(app: FastAPI, run_id: uuid.UUID) -> HexAdkLlm:
    return HexAdkLlm(
        router=app.state.services.providers, ctx=CallContext(run_id=run_id), purpose="coder"
    )


async def test_every_adk_callback_type_is_recorded(
    app: FastAPI, spans: InMemorySpanExporter
) -> None:
    def handler(request: LLMRequest) -> Completion:
        if "explode" in (request.messages[0].content or ""):
            if any(m.role == "tool" for m in request.messages):
                return Completion(content="unreachable")
            return Completion(
                tool_calls=[ToolCall(id="c2", name="explode", arguments={"key": "a"})]
            )
        if "broken model" in (request.messages[0].content or ""):
            raise ProviderError("model down", retryable=False)
        if any(m.role == "tool" for m in request.messages):
            return Completion(content='{"ok": true}', input_tokens=12, output_tokens=3)
        return Completion(
            tool_calls=[ToolCall(id="c1", name="lookup", arguments={"key": "a"})],
            input_tokens=10,
            output_tokens=2,
        )

    use_adapter(app, ScriptedAdapter(handler))
    run_id = await _run(app)
    hub = TelemetryHub(app.state.services, run_id)

    llm = _llm(app, run_id)
    checker = LlmAgent(
        name="checker",
        model=llm,
        instruction="Check the value.",
        tools=[FunctionTool(lookup)],
        output_schema=Verdict,
        output_key="verdict",
        after_model_callback=schema_guard(
            Verdict, llm, key="verdict", fallback=lambda e: Verdict(ok=False)
        ),
    )
    root = hub.instrument(SequentialAgent(name="pipeline", sub_agents=[checker]))
    state, _ = await run_adk(root, message="go")
    assert state["verdict"] == {"ok": True}

    # Error hooks: a failing tool and a failing model (both re-raise: telemetry only observes).
    tool_agent = hub.instrument(
        LlmAgent(
            name="tool_user",
            model=_llm(app, run_id),
            instruction="explode",
            tools=[FunctionTool(explode)],
        )
    )
    with pytest.raises(Exception, match="tool broke"):
        await run_adk(tool_agent, message="go")
    model_agent = hub.instrument(
        LlmAgent(name="model_user", model=_llm(app, run_id), instruction="broken model")
    )
    with pytest.raises(Exception, match="model down"):
        await run_adk(model_agent, message="go")

    events = await _events(app, run_id)
    hooks = {e.payload["hook"] for e in events if e.type == "callback_fired"}
    started = [(e.payload["agent"], e.payload["kind"]) for e in events if e.type == "agent_started"]
    finished = {e.payload["agent"] for e in events if e.type == "agent_finished"}
    assert hooks | {"before_agent_callback", "after_agent_callback"} == set(ADK_HOOKS)
    assert ("pipeline", "sequential") in started and ("checker", "llm") in started
    assert {"pipeline", "checker"} <= finished
    assert all(e.payload["framework"] == "adk" for e in events if "framework" in e.payload)
    after_model = next(
        e
        for e in events
        if e.type == "callback_fired" and e.payload["hook"] == "after_model_callback"
    )
    assert "scripted/scripted-model" in after_model.payload["detail"]
    assert "calls lookup" in after_model.payload["detail"]
    schema = [e.payload for e in events if e.type == "schema_validated"]
    assert schema == [
        {"agent": "checker", "schema_name": "Verdict", "status": "valid", "errors": []}
    ]
    seqs = [e.seq for e in events]
    assert seqs == list(range(1, len(seqs) + 1))

    # ADK's own spans carry our attributes.
    attrs = [dict(s.attributes or {}) for s in spans.get_finished_spans()]
    assert any(
        a.get("agent.framework") == "adk" and a.get("hexmind.run_id") == str(run_id) for a in attrs
    )
    assert any(a.get("llm.provider") == "scripted" for a in attrs)
    assert any(a.get("tool.name") == "lookup" for a in attrs)


async def test_model_error_fallback_records_schema_fallback(app: FastAPI) -> None:
    def handler(request: LLMRequest) -> Completion:
        raise ProviderError("quota", retryable=False)

    use_adapter(app, ScriptedAdapter(handler))
    run_id = await _run(app)
    hub = TelemetryHub(app.state.services, run_id)
    llm = _llm(app, run_id)
    agent = hub.instrument(
        LlmAgent(
            name="judge",
            model=llm,
            instruction="Judge.",
            output_schema=Verdict,
            output_key="verdict",
            after_model_callback=schema_guard(
                Verdict, llm, key="verdict", fallback=lambda e: Verdict(ok=False)
            ),
            on_model_error_callback=model_error_fallback(
                Verdict, key="verdict", fallback=lambda e: Verdict(ok=False)
            ),
        )
    )
    state, _ = await run_adk(agent, message="go")
    assert state["verdict"] == {"ok": False}

    events = await _events(app, run_id)
    hooks = [e.payload["hook"] for e in events if e.type == "callback_fired"]
    assert "on_model_error_callback" in hooks
    (schema,) = [e.payload for e in events if e.type == "schema_validated"]
    assert schema["status"] == "fallback" and "quota" in schema["errors"][0]


async def test_crew_callbacks_record_from_a_worker_thread(
    app: FastAPI, spans: InMemorySpanExporter
) -> None:
    import asyncio

    run_id = await _run(app)
    hub = TelemetryHub(app.state.services, run_id)
    callbacks = hub.crew_callbacks("worker-1", parent="coder")

    def crew_thread() -> None:  # CrewAI calls these on its worker thread
        callbacks.before_kickoff({})
        callbacks.step_callback(SimpleNamespace(tool="write_file"))
        callbacks.task_callback(SimpleNamespace(raw="done"))
        callbacks.after_kickoff("output")

    with callbacks.span():
        await asyncio.to_thread(crew_thread)

    events = await _events(app, run_id)
    assert [(e.type, e.payload.get("hook")) for e in events] == [
        ("agent_started", None),
        ("callback_fired", "step_callback"),
        ("callback_fired", "task_callback"),
        ("agent_finished", None),
    ]
    assert all(e.payload["framework"] == "crewai" and e.agent_id == "worker-1" for e in events)
    assert events[0].payload["kind"] == "crew" and events[0].payload["parent"] == "coder"
    assert events[1].payload["detail"] == "SimpleNamespace: write_file"
    crew_spans = [s for s in spans.get_finished_spans() if s.name == "crewai.crew worker-1"]
    assert crew_spans and crew_spans[0].attributes["agent.framework"] == "crewai"


def test_describe_step() -> None:
    assert describe_step(SimpleNamespace(tool="read_file")) == "SimpleNamespace: read_file"
    assert describe_step(SimpleNamespace(output="final")) == "SimpleNamespace: final"
    assert describe_step(object()) == "object"
