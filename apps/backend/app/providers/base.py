"""Provider-neutral LLM types (plan §4.3). Workers depend on these, never on a provider SDK."""

from decimal import Decimal
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

Purpose = Literal[
    "router", "chat", "summary", "planner", "coder", "reviewer", "judge", "diagnostic"
]


class ToolCall(BaseModel):
    """A function call requested by the model (native tool calling)."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Provider-specific data that must be sent back with this call in later turns
    # (e.g. Gemini's {"google": {"thought_signature": ...}}).
    extra: dict[str, Any] | None = None


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = ""
    # Assistant turns that requested tools, and the matching tool results.
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class LLMRequest(BaseModel):
    messages: list[ChatMessage]
    purpose: Purpose
    json_schema: dict[str, Any] | None = None
    # OpenAI-style function definitions: [{"type": "function", "function": {...}}].
    tools: list[dict[str, Any]] | None = None
    max_tokens: int = 1024
    temperature: float = 0.2
    stop: list[str] | None = None


class Completion(BaseModel):
    """What an adapter returns for one successful attempt."""

    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None
    # Provider API charge; local inference has no API charge (not the same as zero total cost).
    est_cost_usd: Decimal | None = None


class LLMResult(BaseModel):
    provider: str
    model: str
    content: str | None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    est_cost_usd: Decimal | None
    attempts: int
    fallback_from: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class ProviderHealth(BaseModel):
    provider: str
    available: bool
    model: str
    configured: bool = True
    detail: str | None = None


ErrorKind = Literal[
    "timeout",  # retryable
    "connection",  # retryable
    "server",  # retryable (5xx)
    "rate_limit",  # retryable after a short wait (per-minute limits)
    "quota",  # exhausted for a longer period: fall back immediately and cool down
    "auth",  # missing/invalid key: fall back, don't retry
    "model_unavailable",  # model not installed / not found
    "bad_request",
]

RETRYABLE_KINDS = frozenset({"timeout", "connection", "server", "rate_limit"})


class ProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        kind: ErrorKind | None = None,
        retryable: bool | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        if kind is None:
            kind = "server" if retryable else "bad_request"
        self.kind: ErrorKind = kind
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE_KINDS


class ProviderAdapter(Protocol):
    name: str
    model: str

    async def health(self) -> ProviderHealth: ...

    async def complete(self, request: LLMRequest) -> Completion: ...
