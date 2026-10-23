"""ProviderRouter: the only entry point for LLM calls. It retries, logs every call to
`llm_calls`, and emits run events. Provider selection and fallback arrive in M4; for now it
routes to a single adapter.
"""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import LLMCall
from app.events.log import EventType, append_event
from app.providers.base import (
    Completion,
    LLMRequest,
    LLMResult,
    ProviderAdapter,
    ProviderError,
    ProviderHealth,
)


@dataclass(frozen=True)
class CallContext:
    run_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    agent_id: str | None = None


class ProviderRouter:
    def __init__(
        self,
        adapters: list[ProviderAdapter],
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        max_attempts: int = 3,
        backoff_s: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not adapters:
            raise ValueError("at least one provider adapter is required")
        self._adapters = {a.name: a for a in adapters}
        self._default = adapters[0]
        self._sessionmaker = sessionmaker
        self._max_attempts = max_attempts
        self._backoff_s = backoff_s
        self._sleep = sleep

    def adapter(self, name: str) -> ProviderAdapter:
        return self._adapters[name]

    async def health(self) -> dict[str, ProviderHealth]:
        results = await asyncio.gather(*(a.health() for a in self._adapters.values()))
        return {h.provider: h for h in results}

    async def complete(
        self, request: LLMRequest, ctx: CallContext | None = None, *, provider: str | None = None
    ) -> LLMResult:
        ctx = ctx or CallContext()
        adapter = self._adapters[provider] if provider else self._default
        await self._emit(ctx, EventType.LLM_CALL_STARTED, adapter, {"purpose": request.purpose})

        started = time.perf_counter()
        completion: Completion | None = None
        error: str | None = None
        attempts = 0
        while attempts < self._max_attempts:
            attempts += 1
            try:
                completion = await adapter.complete(request)
                break
            except ProviderError as exc:
                error = str(exc)
                if not exc.retryable or attempts >= self._max_attempts:
                    break
                await self._sleep(self._backoff_s * 2 ** (attempts - 1))

        result = LLMResult(
            provider=adapter.name,
            model=adapter.model,
            content=completion.content if completion else None,
            input_tokens=completion.input_tokens if completion else None,
            output_tokens=completion.output_tokens if completion else None,
            latency_ms=round((time.perf_counter() - started) * 1000),
            est_cost_usd=completion.est_cost_usd if completion else None,
            attempts=attempts,
            error=None if completion else error,
        )
        await self._log(request, result, ctx)
        await self._emit(
            ctx,
            EventType.LLM_CALL_COMPLETED,
            adapter,
            {
                "purpose": request.purpose,
                "ok": result.ok,
                "latency_ms": result.latency_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "attempts": result.attempts,
                "error": result.error,
            },
        )
        return result

    async def _log(self, request: LLMRequest, result: LLMResult, ctx: CallContext) -> None:
        # Own session: the call is recorded even if the caller's transaction later fails.
        async with self._sessionmaker.begin() as session:
            session.add(
                LLMCall(
                    run_id=ctx.run_id,
                    task_id=ctx.task_id,
                    purpose=request.purpose,
                    provider=result.provider,
                    model=result.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    latency_ms=result.latency_ms,
                    est_cost_usd=result.est_cost_usd,
                    attempts=result.attempts,
                    fallback_from=result.fallback_from,
                    error=result.error,
                )
            )

    async def _emit(
        self, ctx: CallContext, type: EventType, adapter: ProviderAdapter, payload: dict
    ) -> None:
        if ctx.run_id is None:
            return
        async with self._sessionmaker.begin() as session:
            await append_event(
                session,
                ctx.run_id,
                type,
                agent_id=ctx.agent_id,
                task_id=ctx.task_id,
                payload={"provider": adapter.name, "model": adapter.model, **payload},
            )
