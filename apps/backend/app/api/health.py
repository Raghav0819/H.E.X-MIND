import asyncio
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from app import __version__
from app.api.deps import ProviderRouterDep
from app.providers.base import ProviderHealth

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    db: Literal["ok", "unavailable"]
    providers: dict[str, ProviderHealth]


async def _db_ok(request: Request) -> bool:
    try:
        async with request.app.state.sessionmaker() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=2.0)
        return True
    except Exception:
        return False


@router.get("/health", response_model=HealthResponse)
async def health(request: Request, providers: ProviderRouterDep) -> HealthResponse:
    """Always 200 while the API process is up; dependency status is reported per component."""
    db_ok, provider_health = await asyncio.gather(_db_ok(request), providers.health())
    return HealthResponse(
        status="ok",
        version=__version__,
        db="ok" if db_ok else "unavailable",
        providers=provider_health,
    )
