"""ProviderRouter: the only entry point for LLM calls (plan §4.3, §8).

Policy (deterministic, configurable; never "provider X is always best"):
- Candidates come from the configured order (optionally per task complexity). Providers without
  credentials are not candidates.
- A candidate is skipped while it cools down after quota exhaustion, or while its (cached)
  health check fails, e.g. Ollama without the model installed.
- Transient errors (timeout, connection, 5xx, per-minute rate limits) are retried with bounded
  exponential backoff that honours Retry-After. Quota, auth and model errors fall back at once.
- Every provider attempt is logged in `llm_calls`; switching providers emits `provider_fallback`.
"""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import LLMCall
from app.events.log import EventType, append_event
from app.providers.base import (
    Completion,
    ErrorKind,
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
    # Task complexity, used by the selection policy when per-complexity orders are configured.
    complexity: str | None = None


@dataclass
class _Attempt:
    result: LLMResult
    kind: ErrorKind | None
    retry_after: float | None


class ProviderRouter:
    def __init__(
        self,
        adapters: list[ProviderAdapter],
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        order: list[str] | None = None,
        order_by_complexity: dict[str, list[str]] | None = None,
        max_attempts: int = 3,
        backoff_s: float = 0.5,
        max_backoff_s: float = 20.0,
        quota_cooldown_s: float = 300.0,
        health_ttl_s: float = 60.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not adapters:
            raise ValueError("at least one provider adapter is required")
        self._adapters = {a.name: a for a in adapters}
        self._order = [n for n in (order or [a.name for a in adapters]) if n in self._adapters]
        self._order_by_complexity = {
            k: [n for n in v if n in self._adapters] for k, v in (order_by_complexity or {}).items()
        }
        self._sessionmaker = sessionmaker
        self._max_attempts = max_attempts
        self._backoff_s = backoff_s
        self._max_backoff_s = max_backoff_s
        self._quota_cooldown_s = quota_cooldown_s
        self._health_ttl_s = health_ttl_s
        self._sleep = sleep
        self._clock = clock
        self._cooldown_until: dict[str, float] = {}
        self._cooldown_reason: dict[str, str] = {}
        self._health_cache: dict[str, tuple[float, ProviderHealth]] = {}

    def adapter(self, name: str) -> ProviderAdapter:
        return self._adapters[name]

    @property
    def names(self) -> list[str]:
        return list(self._adapters)

    # ---------- status ----------

    async def health(self) -> dict[str, ProviderHealth]:
        results = await asyncio.gather(*(a.health() for a in self._adapters.values()))
        now = self._clock()
        for health in results:
            self._health_cache[health.provider] = (now, health)
        return {h.provider: h for h in results}

    async def status(self) -> dict[str, dict[str, Any]]:
        """Health plus policy state (order, cooldowns, last rate-limit headers) per provider."""
        health = await self.health()
        now = self._clock()
        return {
            name: {
                "health": health[name],
                "order_position": self._order.index(name) if name in self._order else None,
                "cooldown_s": max(0, round(self._cooldown_until.get(name, 0) - now)),
                "cooldown_reason": self._cooldown_reason.get(name)
                if self._cooldown_until.get(name, 0) > now
                else None,
                "rate_limit": getattr(self._adapters[name], "rate_limit", {}) or {},
            }
            for name in self._adapters
        }

    def candidates(self, complexity: str | None) -> list[ProviderAdapter]:
        order = (complexity and self._order_by_complexity.get(complexity)) or self._order
        return [
            self._adapters[name]
            for name in order
            if getattr(self._adapters[name], "configured", True)
        ]

    async def _ineligible_reason(self, adapter: ProviderAdapter) -> str | None:
        now = self._clock()
        until = self._cooldown_until.get(adapter.name, 0)
        if until > now:
            return f"cooling down for {round(until - now)}s ({self._cooldown_reason[adapter.name]})"
        cached = self._health_cache.get(adapter.name)
        if cached is None or now - cached[0] > self._health_ttl_s:
            health = await adapter.health()
            self._health_cache[adapter.name] = (now, health)
        else:
            health = cached[1]
        return (
            None if health.available else f"unavailable: {health.detail or 'health check failed'}"
        )

    # ---------- completion ----------

    async def complete(
        self, request: LLMRequest, ctx: CallContext | None = None, *, provider: str | None = None
    ) -> LLMResult:
        """Complete via the policy chain, or via one explicit provider (no fallback)."""
        ctx = ctx or CallContext()
        if provider is not None:
            return (await self._attempt(self._adapters[provider], request, ctx, None)).result

        chain = self.candidates(ctx.complexity)
        first_failed: str | None = None
        previous: tuple[str, str] | None = None  # (provider, why we moved on)
        last: _Attempt | None = None
        skipped: list[str] = []

        for adapter in chain:
            reason = await self._ineligible_reason(adapter)
            if reason is not None:
                skipped.append(f"{adapter.name}: {reason}")
                first_failed = first_failed or adapter.name
                previous = (adapter.name, reason)
                continue
            if previous is not None:
                await self._emit_fallback(ctx, previous[0], adapter.name, previous[1])
            last = await self._attempt(adapter, request, ctx, first_failed)
            if last.result.ok:
                return last.result
            if last.kind == "quota":
                self._cool_down(adapter.name, last.retry_after, "quota exhausted")
            elif last.kind == "auth":
                self._cool_down(adapter.name, self._quota_cooldown_s, "credentials rejected")
            elif last.kind == "model_unavailable":
                # A model can be listed yet refuse requests (e.g. retired for new users).
                self._cool_down(adapter.name, self._quota_cooldown_s, "model unavailable")
            first_failed = first_failed or adapter.name
            previous = (adapter.name, f"{last.kind or 'error'}: {last.result.error}")

        if last is not None:
            return last.result
        # Nothing was attempted: no configured, eligible provider.
        error = "no eligible provider" + (f" ({'; '.join(skipped)})" if skipped else "")
        result = LLMResult(
            provider="none",
            model="none",
            content=None,
            input_tokens=None,
            output_tokens=None,
            latency_ms=0,
            est_cost_usd=None,
            attempts=0,
            error=error,
        )
        await self._log(request, result, ctx)
        return result

    def _cool_down(self, name: str, seconds: float | None, reason: str) -> None:
        """Skip a provider for a while: the provider's Retry-After if given, else the default."""
        duration = seconds if seconds and seconds > 0 else self._quota_cooldown_s
        self._cooldown_until[name] = self._clock() + duration
        self._cooldown_reason[name] = reason

    async def _attempt(
        self,
        adapter: ProviderAdapter,
        request: LLMRequest,
        ctx: CallContext,
        fallback_from: str | None,
    ) -> _Attempt:
        await self._emit(ctx, EventType.LLM_CALL_STARTED, adapter, {"purpose": request.purpose})
        started = time.perf_counter()
        completion: Completion | None = None
        error: ProviderError | None = None
        attempts = 0
        while attempts < self._max_attempts:
            attempts += 1
            try:
                completion = await adapter.complete(request)
                break
            except ProviderError as exc:
                error = exc
                if not exc.retryable or attempts >= self._max_attempts:
                    break
                delay = self._backoff_s * 2 ** (attempts - 1)
                if exc.retry_after is not None:
                    delay = max(delay, exc.retry_after)
                await self._sleep(min(delay, self._max_backoff_s))

        result = LLMResult(
            provider=adapter.name,
            model=adapter.model,
            content=completion.content if completion else None,
            tool_calls=completion.tool_calls if completion else [],
            input_tokens=completion.input_tokens if completion else None,
            output_tokens=completion.output_tokens if completion else None,
            latency_ms=round((time.perf_counter() - started) * 1000),
            est_cost_usd=completion.est_cost_usd if completion else None,
            attempts=attempts,
            fallback_from=fallback_from,
            error=None if completion else str(error),
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
        return _Attempt(
            result,
            None if completion else (error.kind if error else None),
            error.retry_after if error else None,
        )

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

    async def _emit_fallback(self, ctx: CallContext, source: str, target: str, reason: str) -> None:
        if ctx.run_id is None:
            return
        async with self._sessionmaker.begin() as session:
            await append_event(
                session,
                ctx.run_id,
                EventType.PROVIDER_FALLBACK,
                agent_id=ctx.agent_id,
                task_id=ctx.task_id,
                payload={"from_provider": source, "to_provider": target, "reason": reason[:300]},
            )
