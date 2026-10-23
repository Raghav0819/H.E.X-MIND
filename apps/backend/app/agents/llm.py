"""CrewAI LLM adapter: every agent model call goes through our ProviderRouter (plan §0 #3), so
it is logged in `llm_calls`, emits run events, and gets provider retry/fallback.

CrewAI runs agents on worker threads; `call` hands each request to the server event loop and
waits for the result there.
"""

import asyncio
from typing import Any

from crewai.llms.base_llm import BaseLLM
from pydantic import PrivateAttr

from app.providers.base import ChatMessage, LLMRequest, Purpose
from app.providers.router import CallContext, ProviderRouter

_ROLE_MAP = {"system": "system", "user": "user", "assistant": "assistant"}


class ProviderCallFailed(RuntimeError):
    pass


class HexLLM(BaseLLM):
    _router: ProviderRouter = PrivateAttr()
    _loop: asyncio.AbstractEventLoop = PrivateAttr()
    _ctx: CallContext = PrivateAttr()
    _purpose: Purpose = PrivateAttr()
    _max_tokens: int = PrivateAttr()

    def __init__(
        self,
        *,
        router: ProviderRouter,
        loop: asyncio.AbstractEventLoop,
        ctx: CallContext,
        purpose: Purpose,
        max_tokens: int = 2048,
        **data: Any,
    ) -> None:
        super().__init__(model=f"hexmind-{purpose}", **data)
        self._router = router
        self._loop = loop
        self._ctx = ctx
        self._purpose = purpose
        self._max_tokens = max_tokens

    def call(
        self,
        messages: Any,
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
    ) -> str:
        stop = list(self.stop) if getattr(self, "stop", None) else None
        request = LLMRequest(
            purpose=self._purpose,
            messages=to_chat_messages(messages),
            max_tokens=self._max_tokens,
            temperature=0.2,
            stop=stop,
        )
        future = asyncio.run_coroutine_threadsafe(
            self._router.complete(request, self._ctx), self._loop
        )
        result = future.result()
        if not result.ok or result.content is None:
            raise ProviderCallFailed(f"{result.provider} call failed: {result.error}")
        return truncate_at_stop(result.content, stop)

    def supports_function_calling(self) -> bool:
        return False  # text ReAct works with every provider, including small local models

    def supports_stop_words(self) -> bool:
        return True

    def get_context_window_size(self) -> int:
        return 8192


def to_chat_messages(messages: Any) -> list[ChatMessage]:
    if isinstance(messages, str):
        return [ChatMessage(role="user", content=messages)]
    converted = []
    for message in messages:
        role = _ROLE_MAP.get(message.get("role", "user"), "user")
        content = message.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        converted.append(ChatMessage(role=role, content=content))  # type: ignore[arg-type]
    return converted


def truncate_at_stop(text: str, stop: list[str] | None) -> str:
    """Providers that ignore stop sequences may run past `Observation:`; cut there."""
    if not stop:
        return text
    cut = min((i for s in stop if (i := text.find(s)) >= 0), default=-1)
    return text if cut < 0 else text[:cut]
