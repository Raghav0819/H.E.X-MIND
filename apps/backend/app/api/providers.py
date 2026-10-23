from fastapi import APIRouter, HTTPException, status

from app.api.deps import ProviderRouterDep
from app.providers.base import ChatMessage, LLMRequest, LLMResult, ProviderHealth

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("", response_model=dict[str, ProviderHealth])
async def list_providers(providers: ProviderRouterDep) -> dict[str, ProviderHealth]:
    return await providers.health()


@router.post("/{name}/test", response_model=LLMResult)
async def test_provider(name: str, providers: ProviderRouterDep) -> LLMResult:
    """Make one small real call through the router (logged to llm_calls like any other)."""
    try:
        providers.adapter(name)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown provider '{name}'") from None
    request = LLMRequest(
        purpose="diagnostic",
        messages=[ChatMessage(role="user", content="Reply with exactly one word: ready")],
        max_tokens=8,
        temperature=0,
    )
    return await providers.complete(request, provider=name)
