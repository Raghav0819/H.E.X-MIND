import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.context.manager import ContextManager
from app.graph.background import BackgroundTasks
from app.memory.store import Memory
from app.providers.router import ProviderRouter

# (services, run_id, *, requires_planning, requires_review) -> None
RunExecutor = Callable[..., Awaitable[None]]


@dataclass
class Services:
    """Dependencies shared by graph nodes. Nodes open their own short transactions."""

    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    providers: ProviderRouter
    context: ContextManager
    background: BackgroundTasks
    memory: Memory | None = None
    # Runs a run in the background; replaceable so conversation tests need no agents.
    run_executor: RunExecutor | None = None

    def launch_run(
        self, run_id: uuid.UUID, *, requires_planning: bool, requires_review: bool
    ) -> None:
        from app.graph.run import execute_run

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
