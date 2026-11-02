from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.a2a.client import CrewServiceProcess, a2a_http_client
from app.api import a2a, conversations, health, projects, providers, runs, tasks
from app.auth import require_token
from app.chat.service import ChatService
from app.config import Settings, get_settings
from app.context.manager import ContextManager
from app.db.session import create_engine, create_sessionmaker
from app.memory.store import Memory, OllamaEmbedding
from app.orchestration.background import BackgroundTasks
from app.orchestration.services import Services
from app.providers.factory import build_providers
from app.telemetry.tracing import setup_tracing


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_tracing(settings)
    engine = create_engine(settings.database_url)
    sessionmaker = create_sessionmaker(engine)
    providers_router, adapters = build_providers(settings, sessionmaker)
    memory = None
    if settings.memory_enabled:
        memory = Memory(
            settings.data_dir / "chroma",
            OllamaEmbedding(settings.ollama_url, settings.embedding_model),
        )
    services = Services(
        settings=settings,
        sessionmaker=sessionmaker,
        providers=providers_router,
        context=ContextManager(settings.context_budget_tokens),
        background=BackgroundTasks(),
        memory=memory,
        a2a_http=a2a_http_client(settings),
    )
    crew_service = CrewServiceProcess(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.crew_service_autostart:
            await crew_service.start(services.a2a_http)
        yield
        await services.background.cancel_all()
        crew_service.stop()
        await services.a2a_http.aclose()
        for adapter in adapters:
            await adapter.aclose()
        await engine.dispose()

    app = FastAPI(title="H.E.X Mind Backend", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.services = services
    app.state.provider_router = services.providers
    app.state.chat = ChatService(services)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    for module in (health, projects, runs, providers, conversations, tasks, a2a):
        app.include_router(module.router, prefix="/api", dependencies=[Depends(require_token)])
    return app
