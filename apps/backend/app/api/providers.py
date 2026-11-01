from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.deps import ProviderRouterDep, SettingsDep
from app.providers.base import ChatMessage, LLMRequest, LLMResult, ProviderHealth

router = APIRouter(prefix="/providers", tags=["providers"])


class ProviderStatus(BaseModel):
    health: ProviderHealth
    order_position: int | None
    cooldown_s: int
    cooldown_reason: str | None
    rate_limit: dict[str, str]


class ProvidersOut(BaseModel):
    order: list[str]
    order_by_complexity: dict[str, list[str]]
    providers: dict[str, ProviderStatus]


@router.get("", response_model=ProvidersOut)
async def list_providers(providers: ProviderRouterDep, settings: SettingsDep) -> dict[str, Any]:
    """Health, policy order, quota cooldowns and latest rate-limit headers. Never key values."""
    return {
        "order": settings.provider_order,
        "order_by_complexity": settings.provider_order_by_complexity,
        "providers": await providers.status(),
    }


@router.post("/{name}/test", response_model=LLMResult)
async def test_provider(name: str, providers: ProviderRouterDep) -> LLMResult:
    """Make one small real call to this provider (logged to llm_calls like any other)."""
    try:
        providers.adapter(name)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown provider '{name}'") from None
    request = LLMRequest(
        purpose="diagnostic",
        messages=[ChatMessage(role="user", content="Reply with exactly one word: ready")],
        # Reasoning models (e.g. gpt-oss) spend tokens thinking before they answer.
        max_tokens=256,
        temperature=0,
    )
    return await providers.complete(request, provider=name)
