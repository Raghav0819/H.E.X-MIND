import json
import re
import uuid
from decimal import Decimal
from typing import Any

import httpx

from app.providers.base import (
    ChatMessage,
    Completion,
    LLMRequest,
    ProviderError,
    ProviderHealth,
    ToolCall,
)


class OllamaAdapter:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        num_ctx: int = 8192,
        timeout_s: float = 600.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._num_ctx = num_ctx
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> ProviderHealth:
        try:
            response = await self._client.get("/api/tags", timeout=2.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return ProviderHealth(
                provider=self.name, available=False, model=self.model, detail=str(exc) or "error"
            )
        installed = {m.get("name") for m in response.json().get("models", [])}
        if self.model not in installed:
            return ProviderHealth(
                provider=self.name,
                available=False,
                model=self.model,
                detail=f"model not installed (run: ollama pull {self.model})",
            )
        return ProviderHealth(provider=self.name, available=True, model=self.model)

    async def complete(self, request: LLMRequest) -> Completion:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [_to_ollama(m) for m in request.messages],
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
                "num_ctx": self._num_ctx,
            },
        }
        if request.json_schema is not None:
            body["format"] = request.json_schema
        if request.tools:
            body["tools"] = request.tools
        if request.stop:
            body["options"]["stop"] = request.stop

        try:
            response = await self._client.post("/api/chat", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError(f"timeout: {exc}", kind="timeout") from exc
        except httpx.TransportError as exc:
            raise ProviderError(f"connection error: {exc}", kind="connection") from exc

        if response.status_code != 200:
            text = response.text[:300]
            if response.status_code == 404 or "not found" in text:
                kind = "model_unavailable"
            elif "does not support tools" in text:
                kind = "bad_request"
            elif response.status_code >= 500 or response.status_code in (408, 429):
                kind = "server"
            else:
                kind = "bad_request"
            raise ProviderError(f"HTTP {response.status_code}: {text}", kind=kind)  # type: ignore[arg-type]

        data = response.json()
        message = data.get("message", {})
        content = message.get("content") or ""
        tool_calls = [_from_ollama_call(call) for call in message.get("tool_calls") or []]
        if request.tools and not tool_calls:
            # Some models (e.g. qwen2.5-coder) print the call as JSON text instead of using
            # Ollama's structured tool_calls; recover it, but only for tools actually offered.
            offered = {t.get("function", {}).get("name") for t in request.tools}
            tool_calls = text_tool_calls(content, offered)
            if tool_calls:
                content = ""
        return Completion(
            content=content,
            tool_calls=tool_calls,
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            est_cost_usd=Decimal(0),
        )


def _to_ollama(message: ChatMessage) -> dict[str, Any]:
    out: dict[str, Any] = {"role": message.role, "content": message.content or ""}
    if message.tool_calls:
        out["tool_calls"] = [
            {"function": {"name": c.name, "arguments": c.arguments}} for c in message.tool_calls
        ]
    if message.role == "tool" and message.name:
        out["tool_name"] = message.name
    return out


_TOOL_CALL_TAG = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def text_tool_calls(content: str, offered: set[str | None]) -> list[ToolCall]:
    """Tool calls a model wrote as JSON text: a bare object or list, a ```json fence, or
    <tool_call> tags. Anything else, or a name that was not offered, yields no calls."""
    text = content.strip()
    tagged = _TOOL_CALL_TAG.findall(text)
    candidates = tagged or [_FENCE.sub(r"\1", text)]
    calls: list[ToolCall] = []
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except ValueError:
            return []
        for item in parsed if isinstance(parsed, list) else [parsed]:
            if not isinstance(item, dict):
                return []
            name = item.get("name")
            arguments = item.get("arguments", item.get("parameters", {}))
            if name not in offered or not isinstance(arguments, dict):
                return []
            calls.append(
                ToolCall(id=f"call_{uuid.uuid4().hex[:12]}", name=name, arguments=arguments)
            )
    return calls


def _from_ollama_call(call: dict[str, Any]) -> ToolCall:
    function = call.get("function", {})
    arguments = function.get("arguments") or {}
    if isinstance(arguments, str):  # some models return a JSON string
        try:
            arguments = json.loads(arguments)
        except ValueError:
            arguments = {"_raw": arguments}
    return ToolCall(
        id=call.get("id") or f"call_{uuid.uuid4().hex[:12]}",
        name=function.get("name", ""),
        arguments=arguments,
    )
