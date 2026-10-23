import json
import uuid
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import AgentEvent, LLMCall
from app.providers.base import (
    ChatMessage,
    Completion,
    LLMRequest,
    ProviderError,
    ProviderHealth,
)
from app.providers.ollama import OllamaAdapter
from app.providers.router import CallContext, ProviderRouter

REQUEST = LLMRequest(purpose="diagnostic", messages=[ChatMessage(role="user", content="hi")])


def _ollama(handler) -> OllamaAdapter:
    return OllamaAdapter(
        "http://ollama.test", "qwen2.5-coder:7b", transport=httpx.MockTransport(handler)
    )


# ---------- Ollama adapter ----------


async def test_ollama_complete_parses_response_and_sends_options() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "ready"},
                "prompt_eval_count": 12,
                "eval_count": 3,
            },
        )

    completion = await _ollama(handler).complete(
        REQUEST.model_copy(update={"json_schema": {"type": "object"}})
    )
    assert completion == Completion(
        content="ready", input_tokens=12, output_tokens=3, est_cost_usd=Decimal(0)
    )
    assert seen["model"] == "qwen2.5-coder:7b"
    assert seen["stream"] is False
    assert seen["format"] == {"type": "object"}
    assert seen["options"]["num_predict"] == REQUEST.max_tokens


@pytest.mark.parametrize(("status", "retryable"), [(500, True), (429, True), (400, False)])
async def test_ollama_http_errors(status: int, retryable: bool) -> None:
    adapter = _ollama(lambda _: httpx.Response(status, text="boom"))
    with pytest.raises(ProviderError) as exc:
        await adapter.complete(REQUEST)
    assert exc.value.retryable is retryable


async def test_ollama_connection_error_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ProviderError) as exc:
        await _ollama(handler).complete(REQUEST)
    assert exc.value.retryable


async def test_ollama_health_checks_model_is_installed() -> None:
    installed = _ollama(
        lambda _: httpx.Response(200, json={"models": [{"name": "qwen2.5-coder:7b"}]})
    )
    missing = _ollama(lambda _: httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]}))
    assert (await installed.health()).available
    health = await missing.health()
    assert not health.available and "ollama pull" in (health.detail or "")


# ---------- Provider router ----------


class FakeAdapter:
    name = "fake"
    model = "fake-model"

    def __init__(self, outcomes: list[Completion | ProviderError]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, available=True, model=self.model)

    async def complete(self, request: LLMRequest) -> Completion:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, ProviderError):
            raise outcome
        return outcome


async def _no_sleep(_: float) -> None:
    return None


async def _llm_calls(app: FastAPI) -> list[LLMCall]:
    async with app.state.sessionmaker() as session:
        return list(await session.scalars(select(LLMCall)))


async def test_router_retries_retryable_errors_and_logs_call(app: FastAPI) -> None:
    adapter = FakeAdapter(
        [
            ProviderError("timeout", retryable=True),
            Completion(content="ok", input_tokens=5, output_tokens=1),
        ]
    )
    router = ProviderRouter([adapter], app.state.sessionmaker, sleep=_no_sleep)

    result = await router.complete(REQUEST)

    assert result.ok and result.content == "ok" and result.attempts == 2
    [logged] = await _llm_calls(app)
    assert (logged.provider, logged.model, logged.purpose) == ("fake", "fake-model", "diagnostic")
    assert (logged.input_tokens, logged.output_tokens, logged.attempts) == (5, 1, 2)
    assert logged.error is None


async def test_router_stops_on_non_retryable_error(app: FastAPI) -> None:
    adapter = FakeAdapter([ProviderError("bad request", retryable=False)])
    router = ProviderRouter([adapter], app.state.sessionmaker, sleep=_no_sleep)

    result = await router.complete(REQUEST)

    assert not result.ok and result.error == "bad request" and result.attempts == 1
    assert result.input_tokens is None  # never invented
    [logged] = await _llm_calls(app)
    assert logged.error == "bad request"


async def test_router_gives_up_after_max_attempts(app: FastAPI) -> None:
    adapter = FakeAdapter([ProviderError("429", retryable=True)] * 3)
    router = ProviderRouter([adapter], app.state.sessionmaker, max_attempts=3, sleep=_no_sleep)
    result = await router.complete(REQUEST)
    assert not result.ok and result.attempts == 3 and adapter.calls == 3


async def test_router_emits_run_events(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path
) -> None:
    project = (await client.post("/api/projects", json={"workspace_path": str(workspace)})).json()
    run = (await client.post("/api/runs", json={"project_id": project["id"], "title": "t"})).json()
    run_id = uuid.UUID(run["id"])
    router = ProviderRouter(
        [FakeAdapter([Completion(content="ok")])], app.state.sessionmaker, sleep=_no_sleep
    )

    await router.complete(REQUEST, CallContext(run_id=run_id, agent_id="coder_01"))

    async with app.state.sessionmaker() as session:
        events = list(
            await session.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.seq)
            )
        )
    assert [e.type for e in events] == ["run_created", "llm_call_started", "llm_call_completed"]
    assert events[2].agent_id == "coder_01"
    assert events[2].payload["ok"] is True
    [logged] = await _llm_calls(app)
    assert logged.run_id == run_id


async def test_provider_test_endpoint_uses_router(app: FastAPI, client: httpx.AsyncClient) -> None:
    app.state.provider_router = ProviderRouter(
        [FakeAdapter([Completion(content="ready")])], app.state.sessionmaker, sleep=_no_sleep
    )
    response = await client.post("/api/providers/fake/test")
    assert response.status_code == 200
    assert response.json()["content"] == "ready"
    assert len(await _llm_calls(app)) == 1
    assert (await client.post("/api/providers/nope/test")).status_code == 404
