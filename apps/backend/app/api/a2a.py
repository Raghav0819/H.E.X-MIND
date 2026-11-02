from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.a2a.client import agent_cards

router = APIRouter(prefix="/a2a", tags=["a2a"])


@router.get("/agents")
async def list_agents(request: Request) -> list[dict[str, Any]]:
    """The CrewAI crews' A2A Agent Cards, fetched live from the crew service."""
    http = request.app.state.services.a2a_http
    if http is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "A2A client not configured")
    return await agent_cards(http)
