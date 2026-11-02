import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.context.manager import ContextManager
from app.memory.store import Memory
from app.orchestration.background import BackgroundTasks
from app.providers.router import ProviderRouter

# (services, run_id, *, requires_planning, requires_review) -> None
RunExecutor = Callable[..., Awaitable[None]]


@dataclass
class Services:
    """Dependencies shared by the agents. Steps open their own short transactions."""

    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    providers: ProviderRouter
    context: ContextManager
    background: BackgroundTasks
    memory: Memory | None = None
    # HTTP client for the CrewAI crew A2A service (tests use an in-process ASGI transport).
    a2a_http: httpx.AsyncClient | None = None
    # Runs a run in the background; replaceable so conversation tests need no agents.
    run_executor: RunExecutor | None = None

    def launch_run(
        self, run_id: uuid.UUID, *, requires_planning: bool, requires_review: bool
    ) -> None:
        from app.orchestration.run import execute_run

        executor = self.run_executor or execute_run
        self.background.spawn(
            executor(
                self,
                run_id,
                requires_planning=requires_planning,
                requires_review=requires_review,
            ),
            name=f"run-{run_id}",
        )
