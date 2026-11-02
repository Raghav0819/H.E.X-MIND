"""M4: native tool calling, hosted adapters, selection policy, quota and fallback."""

import json
import uuid
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select

from app.agents.llm import to_chat_messages, to_crewai_tool_call
from app.db.models import AgentEvent, LLMCall
from app.providers.base import (
    ChatMessage,
    Completion,
    LLMRequest,
    ProviderError,
    ProviderHealth,
    ToolCall,
)
from app.providers.ollama import OllamaAdapter
from app.providers.openai_compat import OpenAICompatAdapter
from app.providers.pricing import Pricing
from app.providers.router import CallContext, ProviderRouter

PRICING = Pricing({"models": {"groq/m": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}}})
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    }
]
REQUEST = LLMRequest(purpose="coder", messages=[ChatMessage(role="user", content="hi")])


# ---------- adapters ----------


async def test_ollama_sends_tools_and_parses_tool_calls() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "write_file", "arguments": {"path": "a.js"}}},
                        {"function": {"name": "read_file", "arguments": '{"path": "b.js"}'}},
                    ],
                },
                "prompt_eval_count": 5,
                "eval_count": 2,
            },
        )

    adapter = OllamaAdapter("http://o", "m", transport=httpx.MockTransport(handler))
    request = LLMRequest(
        purpose="coder",
        tools=TOOLS,
        messages=[
            ChatMessage(role="user", content="go"),
            ChatMessage(
                role="assistant",
                content=None,
                tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "x"})],
            ),
            ChatMessage(role="tool", content="file text", tool_call_id="c1", name="read_file"),
        ],
    )
    completion = await adapter.complete(request)

    assert seen["tools"] == TOOLS
    assert seen["messages"][1]["tool_calls"] == [
        {"function": {"name": "read_file", "arguments": {"path": "x"}}}
    ]
    assert seen["messages"][2] == {"role": "tool", "content": "file text", "tool_name": "read_file"}
    assert [(c.name, c.arguments) for c in completion.tool_calls] == [
        ("write_file", {"path": "a.js"}),
        ("read_file", {"path": "b.js"}),
    ]
    assert all(c.id.startswith("call_") for c in completion.tool_calls)


def _hosted(handler, *, api_key: str | None = "secret-key") -> OpenAICompatAdapter:
    return OpenAICompatAdapter(
        name="groq",
        base_url="https://hosted.test/v1",
        api_key=api_key,
        model="m",
        pricing=PRICING,
        transport=httpx.MockTransport(handler),
    )


async def test_hosted_request_and_response_mapping() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"x-ratelimit-remaining-requests": "99", "x-ratelimit-reset-tokens": "7.6s"},
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_abc",
                                    "type": "function",
                                    "function": {
                                        "name": "write_file",
                                        "arguments": '{"path": "a.js"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            },
        )

    adapter = _hosted(handler)
    request = LLMRequest(
        purpose="coder",
        tools=TOOLS,
        json_schema={"type": "object"},
        messages=[
            ChatMessage(role="user", content="go"),
            ChatMessage(
                role="assistant",
                content=None,
                tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "x"})],
            ),
            ChatMessage(role="tool", content="text", tool_call_id="c1", name="read_file"),
        ],
    )
    completion = await adapter.complete(request)

    assert seen["auth"] == "Bearer secret-key"
    assert seen["url"] == "https://hosted.test/v1/chat/completions"
    body = seen["body"]
    assert body["tools"] == TOOLS and body["tool_choice"] == "auto"
    assert body["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in body["messages"][0]["content"]
    assert body["messages"][2]["tool_calls"][0]["function"] == {
        "name": "read_file",
        "arguments": '{"path": "x"}',
    }
    assert body["messages"][3] == {
        "role": "tool",
        "content": "text",
        "tool_call_id": "c1",
        "name": "read_file",
    }
    assert completion.tool_calls == [
        ToolCall(id="call_abc", name="write_file", arguments={"path": "a.js"})
    ]
    assert completion.est_cost_usd == Decimal("0.002")  # 1000*1/1M + 500*2/1M
    assert adapter.rate_limit == {"remaining-requests": "99", "reset-tokens": "7.6s"}


@pytest.mark.parametrize(
    ("status", "headers", "body", "kind", "retry_after"),
    [
        (401, {}, "invalid api key", "auth", None),
        (400, {}, "API key not valid. Please pass a valid API key.", "auth", None),
        (404, {}, "model not found", "model_unavailable", None),
        (
            429,
            {"retry-after": "12"},
            "Rate limit reached for requests per minute",
            "rate_limit",
            12,
        ),
        (429, {}, "Rate limit reached on tokens per day (TPD)", "quota", None),
        (429, {}, '{"error": {"status": "RESOURCE_EXHAUSTED"}}', "quota", None),
        (429, {"retry-after": "3600"}, "slow down", "quota", 3600),
        (503, {}, "overloaded", "server", None),
        (400, {}, "bad tool schema", "bad_request", None),
    ],
)
async def test_hosted_error_classification(
    status: int, headers: dict, body: str, kind: str, retry_after: float | None
) -> None:
    adapter = _hosted(lambda _: httpx.Response(status, headers=headers, text=body))
    with pytest.raises(ProviderError) as exc:
        await adapter.complete(REQUEST)
    assert exc.value.kind == kind
    assert exc.value.retry_after == retry_after


async def test_hosted_health() -> None:
    unconfigured = _hosted(lambda _: httpx.Response(200), api_key=None)
    health = await unconfigured.health()
    assert (health.configured, health.available) == (False, False)
    assert "HEXMIND_GROQ_API_KEY" in (health.detail or "")
    with pytest.raises(ProviderError) as exc:
        await unconfigured.complete(REQUEST)
    assert exc.value.kind == "auth"

    listed = _hosted(lambda _: httpx.Response(200, json={"data": [{"id": "models/m"}]}))
    assert (await listed.health()).available
    missing = _hosted(lambda _: httpx.Response(200, json={"data": [{"id": "other"}]}))
    assert "not offered" in ((await missing.health()).detail or "")
    rejected = _hosted(lambda _: httpx.Response(401))
    assert (await rejected.health()).detail == "API key rejected"


def test_pricing_estimates_and_never_guesses() -> None:
    assert PRICING.cost("groq", "m", 2_000_000, 1_000_000) == Decimal("4")
    assert PRICING.cost("groq", "unknown", 10, 10) is None
    assert PRICING.cost("groq", "m", None, 10) is None
    assert Pricing.load().cost("ollama", "qwen2.5-coder:7b", 10, 10) is None


# ---------- router policy ----------


class FakeProvider:
    def __init__(
        self,
        name: str,
        outcomes: list[Completion | ProviderError] | None = None,
        *,
        available: bool = True,
        configured: bool = True,
    ) -> None:
        self.name = name
        self.model = f"{name}-model"
        self.outcomes = list(outcomes or [Completion(content=f"from {name}")])
        self.available = available
        self.configured = configured
        self.calls = 0

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name,
            available=self.available,
            model=self.model,
            configured=self.configured,
            detail=None if self.available else "model not installed",
        )

    async def complete(self, request: LLMRequest) -> Completion:
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, ProviderError):
            raise outcome
        return outcome


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _router(app: FastAPI, providers: list[FakeProvider], clock: Clock, **kwargs) -> ProviderRouter:
    return ProviderRouter(
        providers, app.state.sessionmaker, sleep=clock.sleep, clock=clock, **kwargs
    )


async def _calls(app: FastAPI) -> list[LLMCall]:
    async with app.state.sessionmaker() as session:
        return list(await session.scalars(select(LLMCall).order_by(LLMCall.created_at)))


async def test_uses_first_eligible_provider_in_order(app: FastAPI) -> None:
    groq = FakeProvider("groq", configured=False)
    gemini = FakeProvider("gemini")
    ollama = FakeProvider("ollama")
    router = _router(app, [ollama, groq, gemini], Clock(), order=["groq", "gemini", "ollama"])

    result = await router.complete(REQUEST)

    assert result.content == "from gemini" and result.fallback_from is None
    assert groq.calls == 0  # unconfigured: not a candidate, not a fallback
    assert [c.provider for c in await _calls(app)] == ["gemini"]


async def test_quota_exhaustion_falls_back_and_cools_down(app: FastAPI) -> None:
    clock = Clock()
    groq = FakeProvider("groq", [ProviderError("TPD", kind="quota", retry_after=600)])
    ollama = FakeProvider("ollama")
    router = _router(app, [groq, ollama], clock, order=["groq", "ollama"])

    first = await router.complete(REQUEST)
    assert first.content == "from ollama" and first.fallback_from == "groq"
    assert groq.calls == 1  # quota errors are not retried

    second = await router.complete(REQUEST)  # still cooling down: groq is skipped
    assert second.content == "from ollama" and groq.calls == 1
    assert second.fallback_from == "groq"

    clock.now += 601  # Retry-After elapsed
    groq.outcomes = [Completion(content="from groq")]
    third = await router.complete(REQUEST)
    assert third.content == "from groq" and third.fallback_from is None

    calls = await _calls(app)
    assert [(c.provider, c.fallback_from, c.error is not None) for c in calls] == [
        ("groq", None, True),
        ("ollama", "groq", False),
        ("ollama", "groq", False),
        ("groq", None, False),
    ]
    status = await router.status()
    assert status["groq"]["cooldown_s"] == 0


async def test_rate_limits_are_retried_honouring_retry_after(app: FastAPI) -> None:
    clock = Clock()
    groq = FakeProvider(
        "groq",
        [ProviderError("rpm", kind="rate_limit", retry_after=7), Completion(content="ok")],
    )
    router = _router(app, [groq], clock)
    result = await router.complete(REQUEST)
    assert result.content == "ok" and result.attempts == 2
    assert clock.sleeps == [7]


async def test_backoff_is_capped(app: FastAPI) -> None:
    clock = Clock()
    groq = FakeProvider("groq", [ProviderError("rpm", kind="rate_limit", retry_after=90)])
    router = _router(app, [groq], clock, max_backoff_s=20)
    result = await router.complete(REQUEST)
    assert not result.ok and result.attempts == 3
    assert clock.sleeps == [20, 20]


async def test_auth_failure_falls_back_without_retry(app: FastAPI) -> None:
    groq = FakeProvider("groq", [ProviderError("401", kind="auth")])
    ollama = FakeProvider("ollama")
    router = _router(app, [groq, ollama], Clock())
    result = await router.complete(REQUEST)
    assert result.content == "from ollama" and groq.calls == 1
    assert (await router.status())["groq"]["cooldown_reason"] == "credentials rejected"


async def test_unhealthy_provider_is_skipped(app: FastAPI) -> None:
    ollama = FakeProvider("ollama", available=False)
    gemini = FakeProvider("gemini")
    router = _router(app, [ollama, gemini], Clock(), order=["ollama", "gemini"])
    result = await router.complete(REQUEST)
    assert result.content == "from gemini" and result.fallback_from == "ollama"
    assert ollama.calls == 0


async def test_transient_failures_exhaust_then_fall_back(app: FastAPI) -> None:
    groq = FakeProvider("groq", [ProviderError("timeout", kind="timeout")])
    gemini = FakeProvider("gemini")
    router = _router(app, [groq, gemini], Clock())
    result = await router.complete(REQUEST)
    assert result.content == "from gemini" and groq.calls == 3


async def test_all_providers_failing_returns_last_error(app: FastAPI) -> None:
    groq = FakeProvider("groq", [ProviderError("q", kind="quota")])
    gemini = FakeProvider("gemini", [ProviderError("down", kind="bad_request")])
    router = _router(app, [groq, gemini], Clock())
    result = await router.complete(REQUEST)
    assert not result.ok and result.provider == "gemini" and result.error == "down"
    assert result.fallback_from == "groq"


async def test_no_eligible_provider_is_reported(app: FastAPI) -> None:
    router = _router(
        app, [FakeProvider("groq", configured=False), FakeProvider("ollama", available=False)],
        Clock(),
    )  # fmt: skip
    result = await router.complete(REQUEST)
    assert not result.ok and result.provider == "none"
    assert "ollama: unavailable: model not installed" in (result.error or "")


async def test_per_complexity_order(app: FastAPI) -> None:
    ollama, gemini = FakeProvider("ollama"), FakeProvider("gemini")
    router = _router(
        app, [ollama, gemini], Clock(), order=["gemini", "ollama"],
        order_by_complexity={"low": ["ollama", "gemini"]},
    )  # fmt: skip
    low = await router.complete(REQUEST, CallContext(complexity="low"))
    high = await router.complete(REQUEST, CallContext(complexity="high"))
    assert (low.content, high.content) == ("from ollama", "from gemini")


async def test_explicit_provider_bypasses_policy(app: FastAPI) -> None:
    groq = FakeProvider("groq", [ProviderError("q", kind="quota")])
    ollama = FakeProvider("ollama")
    router = _router(app, [groq, ollama], Clock())
    result = await router.complete(REQUEST, provider="groq")
    assert not result.ok and ollama.calls == 0


async def test_fallback_emits_run_event(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path
) -> None:
    project = (await client.post("/api/projects", json={"workspace_path": str(workspace)})).json()
    run = (await client.post("/api/runs", json={"project_id": project["id"], "title": "t"})).json()
    run_id = uuid.UUID(run["id"])
    groq = FakeProvider("groq", [ProviderError("TPD", kind="quota")])
    router = _router(app, [groq, FakeProvider("ollama")], Clock())

    await router.complete(REQUEST, CallContext(run_id=run_id, agent_id="coder_01"))

    async with app.state.sessionmaker() as session:
        events = list(
            await session.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.seq)
            )
        )
    types = [e.type for e in events]
    assert types == [
        "run_created",
        "llm_call_started",
        "llm_call_completed",
        "provider_fallback",
        "llm_call_started",
        "llm_call_completed",
    ]
    fallback = events[3]
    assert fallback.payload["from_provider"] == "groq"
    assert fallback.payload["to_provider"] == "ollama"
    assert fallback.payload["reason"].startswith("quota")
    assert fallback.agent_id == "coder_01"


# ---------- CrewAI bridge ----------


def test_crewai_messages_with_tool_calls_round_trip() -> None:
    messages = to_chat_messages(
        [
            {"role": "system", "content": "s"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path": "a.js"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "text"},
        ]
    )
    assert messages[1].tool_calls == [
        ToolCall(id="c1", name="read_file", arguments={"path": "a.js"})
    ]
    assert messages[1].content is None
    assert (messages[2].role, messages[2].tool_call_id, messages[2].content) == (
        "tool",
        "c1",
        "text",
    )
    assert to_crewai_tool_call(messages[1].tool_calls[0]) == {
        "id": "c1",
        "type": "function",
        "function": {"name": "read_file", "arguments": '{"path": "a.js"}'},
    }


# ---------- API ----------


async def test_providers_api_reports_policy_without_leaking_keys(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.state.services.settings.groq_api_key = SecretStr("gsk_supersecretvalue1234567890")
    groq = FakeProvider("groq")
    groq.rate_limit = {"remaining-requests": "42"}  # type: ignore[attr-defined]
    router = _router(app, [groq, FakeProvider("ollama")], Clock())
    app.state.provider_router = router

    response = await client.get("/api/providers")

    assert response.status_code == 200
    body = response.json()
    assert body["providers"]["groq"]["rate_limit"] == {"remaining-requests": "42"}
    assert body["providers"]["ollama"]["health"]["available"] is True
    assert "supersecret" not in response.text


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            '{"name": "write_file", "arguments": {"path": "a.js"}}',
            [("write_file", {"path": "a.js"})],
        ),
        (
            '```json\n{"name": "write_file", "arguments": {"path": "a.js"}}\n```',
            [("write_file", {"path": "a.js"})],
        ),
        (
            '<tool_call>\n{"name": "read_file", "arguments": {"path": "x"}}\n</tool_call>'
            '<tool_call>{"name": "write_file", "arguments": {"path": "y"}}</tool_call>',
            [("read_file", {"path": "x"}), ("write_file", {"path": "y"})],
        ),
        (
            '[{"name": "write_file", "parameters": {"path": "a.js"}}]',
            [("write_file", {"path": "a.js"})],
        ),
        ('{"name": "rm_rf", "arguments": {}}', []),  # not an offered tool
        ('{"verdict": "approved", "findings": []}', []),  # a JSON answer, not a call
        ("I created the file.", []),
    ],
)
def test_text_tool_calls_are_recovered_only_for_offered_tools(content: str, expected: list) -> None:
    from app.providers.ollama import text_tool_calls

    calls = text_tool_calls(content, {"write_file", "read_file"})
    assert [(c.name, c.arguments) for c in calls] == expected


async def test_ollama_recovers_text_tool_calls_when_tools_were_offered() -> None:
    body = {"message": {"content": '{"name": "write_file", "arguments": {"path": "a.js"}}'}}
    adapter = OllamaAdapter(
        "http://o", "m", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    )
    with_tools = await adapter.complete(REQUEST.model_copy(update={"tools": TOOLS}))
    assert [c.name for c in with_tools.tool_calls] == ["write_file"] and with_tools.content == ""
    without_tools = await adapter.complete(REQUEST)
    assert without_tools.tool_calls == [] and "write_file" in without_tools.content


async def test_listed_but_unavailable_model_falls_back_and_cools_down(app: FastAPI) -> None:
    gemini = FakeProvider("gemini", [ProviderError("404 retired", kind="model_unavailable")])
    ollama = FakeProvider("ollama")
    router = _router(app, [gemini, ollama], Clock())
    assert (await router.complete(REQUEST)).content == "from ollama"
    assert (await router.complete(REQUEST)).content == "from ollama"
    assert gemini.calls == 1  # skipped while cooling down
    assert (await router.status())["gemini"]["cooldown_reason"] == "model unavailable"


# Real error texts seen live (organization id removed).
GROQ_TPM_429 = (
    '{"error":{"message":"Rate limit reached for model `openai/gpt-oss-120b` in organization '
    "`org_x` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 7769, "
    "Requested 2471. Please try again in 16.8s. Need more tokens? Upgrade to Dev Tier today at "
    'https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}'
)


@pytest.mark.parametrize(
    ("body", "kind", "retry_after"),
    [
        (GROQ_TPM_429, "rate_limit", 16.8),  # mentions billing, but it is a per-minute limit
        ("Rate limit on requests per minute (RPM). Please try again in 1m30s.", "rate_limit", 90),
        (
            "Rate limit reached on tokens per day (TPD). Please try again in 7m12.5s.",
            "quota",
            432.5,
        ),
    ],
)
async def test_429_texts_are_classified_from_their_wording(
    body: str, kind: str, retry_after: float
) -> None:
    adapter = _hosted(lambda _: httpx.Response(429, text=body))
    with pytest.raises(ProviderError) as exc:
        await adapter.complete(REQUEST)
    assert exc.value.kind == kind
    assert exc.value.retry_after == pytest.approx(retry_after)


async def test_gemini_tool_calls_round_trip_thought_signatures() -> None:
    sent: list[dict] = []
    signature = {"google": {"thought_signature": "sig-from-gemini"}}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "g1",
                                    "type": "function",
                                    "function": {"name": "read_file", "arguments": "{}"},
                                    "extra_content": signature,
                                }
                            ],
                        }
                    }
                ]
            },
        )

    gemini = OpenAICompatAdapter(
        name="gemini",
        base_url="https://hosted.test/v1",
        api_key="k",
        model="m",
        pricing=PRICING,
        transport=httpx.MockTransport(handler),
        requires_thought_signatures=True,
    )
    completion = await gemini.complete(REQUEST)
    assert completion.tool_calls[0].extra == signature

    history = LLMRequest(
        purpose="coder",
        messages=[
            ChatMessage(role="user", content="go"),
            ChatMessage(role="assistant", content=None, tool_calls=[completion.tool_calls[0]]),
            ChatMessage(role="tool", content="x", tool_call_id="g1"),
            # A call another provider made earlier in the same conversation.
            ChatMessage(
                role="assistant", content=None, tool_calls=[ToolCall(id="q1", name="read_file")]
            ),
            ChatMessage(role="tool", content="y", tool_call_id="q1"),
        ],
    )
    await gemini.complete(history)
    calls = [m["tool_calls"][0] for m in sent[-1]["messages"] if m.get("tool_calls")]
    assert calls[0]["extra_content"] == signature  # Gemini's own signature, preserved
    assert calls[1]["extra_content"] == {
        "google": {"thought_signature": "skip_thought_signature_validator"}
    }


async def test_hexllm_reattaches_extras_crewai_dropped() -> None:
    from app.agents.llm import to_chat_messages

    extras = {"g1": {"google": {"thought_signature": "s"}}}
    crewai_history = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "g1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        }
    ]
    [message] = to_chat_messages(crewai_history, extras)
    assert message.tool_calls is not None and message.tool_calls[0].extra == extras["g1"]


async def test_rate_limit_abbreviations_alone_are_recognized() -> None:
    adapter = _hosted(lambda _: httpx.Response(429, text="Limit exceeded (TPM). Retry shortly."))
    with pytest.raises(ProviderError) as exc:
        await adapter.complete(REQUEST)
    assert exc.value.kind == "rate_limit"
    adapter = _hosted(lambda _: httpx.Response(429, text="Limit exceeded (TPD)."))
    with pytest.raises(ProviderError) as exc:
        await adapter.complete(REQUEST)
    assert exc.value.kind == "quota"


async def test_gemini_retry_delay_sets_a_short_cooldown() -> None:
    padding = '"details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure"}],' * 6
    body = (
        '[{"error": {"code": 429, "message": "You exceeded your current quota, please check your '
        f'plan and billing details.", "status": "RESOURCE_EXHAUSTED", {padding} '
        '"retryDelay": "39s"}}]'
    )
    assert len(body) > 400  # the delay is past the part kept in the message
    adapter = _hosted(lambda _: httpx.Response(429, text=body))
    with pytest.raises(ProviderError) as exc:
        await adapter.complete(REQUEST)
    assert exc.value.kind == "quota"  # fall back now...
    assert exc.value.retry_after == 39  # ...but only skip the provider for 39s


READ_TOOL = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]


def _tool_use_failed(name: str, arguments: object) -> httpx.Response:
    generation = json.dumps({"name": name, "arguments": arguments})
    return httpx.Response(
        400,
        json={
            "error": {
                "message": f"attempted to call tool '{name}' which was not in request.tools",
                "type": "invalid_request_error",
                "code": "tool_use_failed",
                "failed_generation": generation,
            }
        },
    )


async def test_json_wrapped_in_an_unoffered_tool_call_is_salvaged() -> None:
    plan = {"tasks": [{"title": "t"}]}
    adapter = _hosted(lambda request: _tool_use_failed("json", plan))
    request = REQUEST.model_copy(update={"tools": READ_TOOL})
    completion = await adapter.complete(request)
    assert json.loads(completion.content) == plan and completion.tool_calls == []


async def test_failed_calls_to_real_tools_still_fail() -> None:
    adapter = _hosted(lambda request: _tool_use_failed("read_file", {"bad": 1}))
    with pytest.raises(ProviderError) as info:
        await adapter.complete(REQUEST.model_copy(update={"tools": READ_TOOL}))
    assert info.value.kind == "bad_request"
