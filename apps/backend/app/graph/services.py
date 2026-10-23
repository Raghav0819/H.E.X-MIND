from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.context.manager import ContextManager
from app.graph.background import BackgroundTasks
from app.providers.router import ProviderRouter


@dataclass
class Services:
    """Dependencies shared by graph nodes. Nodes open their own short transactions."""

    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    providers: ProviderRouter
    context: ContextManager
    background: BackgroundTasks
