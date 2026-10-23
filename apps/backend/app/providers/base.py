"""Provider-neutral LLM types (plan §4.3). Workers depend on these, never on a provider SDK."""

from decimal import Decimal
from typing import Any, Literal, Protocol

from pydantic import BaseModel

Purpose = Literal[
    "router", "chat", "summary", "planner", "coder", "reviewer", "judge", "diagnostic"
]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    messages: list[ChatMessage]
    purpose: Purpose
    json_schema: dict[str, Any] | None = None
    max_tokens: int = 1024
    temperature: float = 0.2
    stop: list[str] | None = None


class Completion(BaseModel):
    """What an adapter returns for one successful attempt."""

    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    # Provider API charge; local inference has no API charge (not the same as zero total cost).
    est_cost_usd: Decimal | None = None


class LLMResult(BaseModel):
    provider: str
    model: str
    content: str | None
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
    detail: str | None = None


class ProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class ProviderAdapter(Protocol):
    name: str
    model: str

    async def health(self) -> ProviderHealth: ...

    async def complete(self, request: LLMRequest) -> Completion: ...
