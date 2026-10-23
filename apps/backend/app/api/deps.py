from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.session import get_session
from app.providers.router import ProviderRouter

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


def get_provider_router(request: Request) -> ProviderRouter:
    return request.app.state.provider_router


SettingsDep = Annotated[Settings, Depends(get_settings_from_app)]
ProviderRouterDep = Annotated[ProviderRouter, Depends(get_provider_router)]
