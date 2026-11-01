"""Adapter for OpenAI-compatible chat completion APIs: Groq and Gemini (via its OpenAI
compatibility endpoint). One implementation, so both providers behave identically in tool
calling, error classification and accounting."""

import json
import re
import uuid
from typing import Any

import httpx

from app.providers.base import (
    ChatMessage,
    Completion,
    ErrorKind,
    LLMRequest,
    ProviderError,
    ProviderHealth,
    ToolCall,
)
from app.providers.pricing import Pricing

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

# A 429 is a short rate limit (per minute) unless it signals a longer exhaustion.
_PER_MINUTE = re.compile(r"per minute|\bTPM\b|\bRPM\b", re.IGNORECASE)
_QUOTA_HINTS = re.compile(r"per day|daily|\bTPD\b|\bRPD\b|RESOURCE_EXHAUSTED|quota", re.IGNORECASE)
_TRY_AGAIN = re.compile(r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)s", re.IGNORECASE)
_RETRY_DELAY = re.compile(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"')
_LONG_WAIT_S = 120
# Gemini rejects replayed function calls without a thought signature; calls that another
# provider made get Google's documented placeholder.
_SIGNATURE_PLACEHOLDER = {"google": {"thought_signature": "skip_thought_signature_validator"}}


class OpenAICompatAdapter:
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str | None,
        model: str,
        pricing: Pricing,
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
        requires_thought_signatures: bool = False,
    ) -> None:
        self.name = name
        self._requires_signatures = requires_thought_signatures
        self.model = model
        self._api_key = api_key
        self._pricing = pricing
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_s,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )
        # Latest rate-limit headers reported by the provider (shown in provider status).
        self.rate_limit: dict[str, str] = {}

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> ProviderHealth:
        if not self.configured:
            return ProviderHealth(
                provider=self.name,
                available=False,
                configured=False,
                model=self.model,
                detail=f"no API key (set HEXMIND_{self.name.upper()}_API_KEY)",
            )
        try:
            response = await self._client.get("/models", timeout=5.0)
        except httpx.HTTPError as exc:
            return ProviderHealth(
                provider=self.name, available=False, model=self.model, detail=str(exc) or "error"
            )
        if response.status_code in (401, 403):
            return ProviderHealth(
                provider=self.name, available=False, model=self.model, detail="API key rejected"
            )
        if response.status_code != 200:
            return ProviderHealth(
                provider=self.name,
                available=False,
                model=self.model,
                detail=f"HTTP {response.status_code}",
            )
        ids = {m.get("id", "").removeprefix("models/") for m in response.json().get("data", [])}
        if self.model not in ids:
            return ProviderHealth(
                provider=self.name,
                available=False,
                model=self.model,
                detail="model not offered by the provider",
            )
        return ProviderHealth(provider=self.name, available=True, model=self.model)

    async def complete(self, request: LLMRequest) -> Completion:
        if not self.configured:
            raise ProviderError(f"{self.name}: no API key configured", kind="auth")

        messages = [_to_openai(m, self._requires_signatures) for m in request.messages]
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.tools:
            body["tools"] = request.tools
            body["tool_choice"] = "auto"
        if request.stop:
            body["stop"] = request.stop[:4]
        if request.json_schema is not None:
            # json_object is supported widely; the schema itself goes in the instructions.
            body["response_format"] = {"type": "json_object"}
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": "Respond with a single JSON object matching this JSON Schema:\n"
                    + json.dumps(request.json_schema),
                },
            )

        try:
            response = await self._client.post("/chat/completions", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError(f"{self.name} timeout: {exc}", kind="timeout") from exc
        except httpx.TransportError as exc:
            raise ProviderError(f"{self.name} connection error: {exc}", kind="connection") from exc

        self.rate_limit = {
            k.removeprefix("x-ratelimit-"): v
            for k, v in response.headers.items()
            if k.lower().startswith("x-ratelimit-")
        }
        if response.status_code != 200:
            raise _classify(self.name, response)

        data = response.json()
        message = (data.get("choices") or [{}])[0].get("message") or {}
        usage = data.get("usage") or {}
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        return Completion(
            content=message.get("content") or "",
            tool_calls=[_from_openai_call(c) for c in message.get("tool_calls") or []],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            est_cost_usd=self._pricing.cost(self.name, self.model, input_tokens, output_tokens),
        )


def _classify(provider: str, response: httpx.Response) -> ProviderError:
    status = response.status_code
    body = response.text  # classify on the full body; keep the message short
    text = body[:400]
    retry_after = _retry_after(response)
    kind: ErrorKind
    if status in (401, 403) or "API key" in body:
        kind = "auth"
    elif status == 404:
        kind = "model_unavailable"
    elif status == 429:
        if retry_after is None and (match := _TRY_AGAIN.search(body)):
            retry_after = int(match.group(1) or 0) * 60 + float(match.group(2))
        elif retry_after is None and (match := _RETRY_DELAY.search(body)):
            retry_after = float(match.group(1))  # Gemini's RetryInfo, e.g. "retryDelay": "39s"
        long_wait = retry_after is not None and retry_after > _LONG_WAIT_S
        if _PER_MINUTE.search(body) and not long_wait:
            kind = "rate_limit"
        else:
            kind = "quota" if long_wait or _QUOTA_HINTS.search(body) else "rate_limit"
    elif status >= 500:
        kind = "server"
    else:
        kind = "bad_request"
    return ProviderError(f"{provider} HTTP {status}: {text}", kind=kind, retry_after=retry_after)


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_openai(message: ChatMessage, signatures: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        calls = []
        for c in message.tool_calls:
            call: dict[str, Any] = {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
            }
            if c.extra:
                call["extra_content"] = c.extra
            elif signatures:
                call["extra_content"] = _SIGNATURE_PLACEHOLDER
            calls.append(call)
        out["tool_calls"] = calls
    if message.role == "tool":
        out["tool_call_id"] = message.tool_call_id
        if message.name:
            out["name"] = message.name
    if out["content"] is None and message.role != "assistant":
        out["content"] = ""
    return out


def _from_openai_call(call: dict[str, Any]) -> ToolCall:
    function = call.get("function", {})
    raw = function.get("arguments") or "{}"
    try:
        arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except ValueError:
        arguments = {"_raw": raw}
    return ToolCall(
        id=call.get("id") or f"call_{uuid.uuid4().hex[:12]}",
        name=function.get("name", ""),
        arguments=arguments if isinstance(arguments, dict) else {"_raw": arguments},
        extra=call.get("extra_content") or None,
    )
