"""Google ADK model adapter: every ADK agent's model call goes through our ProviderRouter, the
same entry point CrewAI agents use (HexLLM). One router means one place for provider
selection, retry/fallback, cost estimates, `llm_calls` logging and run events, whichever
framework an agent belongs to.

ADK's request/response types (google.genai `Content` with text, function calls and function
responses) are converted to and from our provider-neutral types. Gemini thought signatures
on function calls round-trip via `ToolCall.extra`.
"""

import base64
import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import PrivateAttr

from app.providers.base import ChatMessage, LLMRequest, LLMResult, Purpose, ToolCall
from app.providers.router import CallContext, ProviderRouter


class ProviderCallFailed(RuntimeError):
    pass


class HexAdkLlm(BaseLlm):
    """`model` is a label for traces (e.g. "hexmind-router"); the real provider and model are
    chosen per call by the ProviderRouter and recorded on each `llm_calls` row."""

    _router: ProviderRouter = PrivateAttr()
    _ctx: CallContext = PrivateAttr()
    _purpose: Purpose = PrivateAttr()
    _max_tokens: int = PrivateAttr()
    # The most recent request/result, for callbacks (provider, model, tokens, cost) and for the
    # schema guard's repair call.
    _last_request: LLMRequest | None = PrivateAttr(default=None)
    _last_result: LLMResult | None = PrivateAttr(default=None)

    def __init__(
        self,
        *,
        router: ProviderRouter,
        ctx: CallContext,
        purpose: Purpose,
        max_tokens: int = 2048,
        **data: Any,
    ) -> None:
        super().__init__(model=f"hexmind-{purpose}", **data)
        self._router = router
        self._ctx = ctx
        self._purpose = purpose
        self._max_tokens = max_tokens

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        request = to_provider_request(llm_request, self._purpose, self._max_tokens)
        self._last_request = request
        result = await self._router.complete(request, self._ctx)
        self._last_result = result
        if not result.ok:
            raise ProviderCallFailed(f"{result.provider} call failed: {result.error}")
        yield to_llm_response(result)

    @property
    def last_request(self) -> LLMRequest | None:
        return self._last_request

    @property
    def last_result(self) -> LLMResult | None:
        return self._last_result

    @property
    def router(self) -> ProviderRouter:
        return self._router

    @property
    def ctx(self) -> CallContext:
        return self._ctx


def to_provider_request(llm_request: LlmRequest, purpose: Purpose, max_tokens: int) -> LLMRequest:
    config = llm_request.config
    messages: list[ChatMessage] = []
    system = _system_text(config.system_instruction) if config else ""
    if system:
        messages.append(ChatMessage(role="system", content=system))
    for content in llm_request.contents or []:
        messages.extend(_to_messages(content))

    tools = []
    for declaration in _declarations(config):
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": declaration.name,
                    "description": declaration.description or "",
                    "parameters": _parameters(declaration),
                },
            }
        )

    json_schema = None
    if config and config.response_schema is not None:
        schema = config.response_schema
        json_schema = (
            schema.model_json_schema()
            if isinstance(schema, type) and hasattr(schema, "model_json_schema")
            else None
        )
    if config and config.response_json_schema is not None:
        json_schema = config.response_json_schema  # type: ignore[assignment]

    return LLMRequest(
        purpose=purpose,
        messages=messages,
        tools=tools or None,
        json_schema=json_schema,
        max_tokens=(
            config.max_output_tokens if config and config.max_output_tokens else max_tokens
        ),
        temperature=(config.temperature if config and config.temperature is not None else 0.2),
    )


def to_llm_response(result: LLMResult) -> LlmResponse:
    parts: list[types.Part] = []
    if result.content:
        parts.append(types.Part(text=result.content))
    for call in result.tool_calls:
        part = types.Part(
            function_call=types.FunctionCall(id=call.id, name=call.name, args=call.arguments)
        )
        signature = ((call.extra or {}).get("google") or {}).get("thought_signature")
        if signature and signature != "skip_thought_signature_validator":
            try:
                part.thought_signature = base64.b64decode(signature)
            except ValueError:
                pass
        parts.append(part)
    if not parts:
        parts.append(types.Part(text=""))
    usage = None
    if result.input_tokens is not None or result.output_tokens is not None:
        usage = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=result.input_tokens,
            candidates_token_count=result.output_tokens,
            total_token_count=(result.input_tokens or 0) + (result.output_tokens or 0),
        )
    return LlmResponse(
        content=types.Content(role="model", parts=parts),
        usage_metadata=usage,
        custom_metadata={
            "provider": result.provider,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "est_cost_usd": str(result.est_cost_usd) if result.est_cost_usd is not None else None,
            "fallback_from": result.fallback_from,
        },
    )


def _system_text(instruction: Any) -> str:
    if instruction is None:
        return ""
    if isinstance(instruction, str):
        return instruction
    if isinstance(instruction, types.Content):
        return "\n".join(p.text for p in instruction.parts or [] if p.text)
    if isinstance(instruction, list):
        return "\n".join(_system_text(i) for i in instruction)
    return str(instruction)


def _to_messages(content: types.Content) -> list[ChatMessage]:
    role = "assistant" if content.role == "model" else "user"
    text = "".join(p.text for p in content.parts or [] if p.text and not p.thought)
    calls = [p for p in content.parts or [] if p.function_call]
    responses = [p for p in content.parts or [] if p.function_response]

    messages: list[ChatMessage] = []
    if calls:
        tool_calls = []
        for part in calls:
            fc = part.function_call
            assert fc is not None
            extra = None
            if part.thought_signature:
                extra = {
                    "google": {
                        "thought_signature": base64.b64encode(part.thought_signature).decode()
                    }
                }
            tool_calls.append(
                ToolCall(
                    id=fc.id or f"call_{uuid.uuid4().hex[:12]}",
                    name=fc.name or "",
                    arguments=dict(fc.args or {}),
                    extra=extra,
                )
            )
        messages.append(ChatMessage(role="assistant", content=text or None, tool_calls=tool_calls))
    elif text:
        messages.append(ChatMessage(role=role, content=text))
    for part in responses:
        fr = part.function_response
        assert fr is not None
        messages.append(
            ChatMessage(
                role="tool",
                content=json.dumps(fr.response, default=str) if fr.response is not None else "",
                tool_call_id=fr.id,
                name=fr.name,
            )
        )
    return messages


def _declarations(config: types.GenerateContentConfig | None) -> list[types.FunctionDeclaration]:
    declarations: list[types.FunctionDeclaration] = []
    for tool in config.tools if config and config.tools else []:
        declarations.extend(getattr(tool, "function_declarations", None) or [])
    return declarations


def _parameters(declaration: types.FunctionDeclaration) -> dict[str, Any]:
    if declaration.parameters_json_schema:
        return dict(declaration.parameters_json_schema)  # type: ignore[arg-type]
    if declaration.parameters is not None:
        return _lowercase_types(declaration.parameters.model_dump(exclude_none=True))
    return {"type": "object", "properties": {}}


def _lowercase_types(node: Any) -> Any:
    """genai Schema uses upper-case types ("OBJECT"); JSON Schema uses lower-case."""
    if isinstance(node, dict):
        return {
            k: (v.lower() if k == "type" and isinstance(v, str) else _lowercase_types(v))
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_lowercase_types(v) for v in node]
    return node
