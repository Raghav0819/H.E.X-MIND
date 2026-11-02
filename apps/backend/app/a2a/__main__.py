"""Run the CrewAI crew A2A service: python -m app.a2a"""

import contextlib
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import uvicorn
from starlette.applications import Starlette

from app.a2a.server import build_crew_app
from app.config import get_settings
from app.context.manager import ContextManager
from app.db.session import create_engine, create_sessionmaker
from app.orchestration.background import BackgroundTasks
from app.orchestration.services import Services
from app.providers.factory import build_providers
from app.telemetry.tracing import setup_tracing


def create_crew_service() -> Starlette:
    settings = get_settings()
    setup_tracing(settings)
    engine = create_engine(settings.database_url)
    sessionmaker = create_sessionmaker(engine)
    providers, adapters = build_providers(settings, sessionmaker)
    services = Services(
        settings=settings,
        sessionmaker=sessionmaker,
        providers=providers,
        context=ContextManager(settings.context_budget_tokens),
        background=BackgroundTasks(),
    )
    app = build_crew_app(services)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        yield
        for adapter in adapters:
            await adapter.aclose()
        await engine.dispose()

    app.router.lifespan_context = lifespan
    return app


def main() -> None:
    url = urlparse(get_settings().crew_service_url)
    # No reload: crews start MCP subprocesses, which need the default (Proactor) loop on Windows.
    uvicorn.run(create_crew_service(), host=url.hostname or "127.0.0.1", port=url.port or 8766)


if __name__ == "__main__":
    main()
