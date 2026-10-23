from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import conversations, health, projects, providers, runs, tasks
from app.auth import require_token
from app.chat.service import ChatService
from app.config import Settings, get_settings
from app.context.manager import ContextManager
from app.db.session import create_engine, create_sessionmaker
from app.graph.background import BackgroundTasks
from app.graph.services import Services
from app.memory.store import Memory, OllamaEmbedding
from app.providers.ollama import OllamaAdapter
from app.providers.router import ProviderRouter


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)
    sessionmaker = create_sessionmaker(engine)
    ollama = OllamaAdapter(
        settings.ollama_url,
        settings.ollama_model,
        num_ctx=settings.ollama_num_ctx,
        timeout_s=settings.ollama_timeout_s,
    )
    memory = None
    if settings.memory_enabled:
        memory = Memory(
            settings.data_dir / "chroma",
            OllamaEmbedding(settings.ollama_url, settings.embedding_model),
        )
    services = Services(
        settings=settings,
        sessionmaker=sessionmaker,
        providers=ProviderRouter([ollama], sessionmaker),
        context=ContextManager(settings.context_budget_tokens),
        background=BackgroundTasks(),
        memory=memory,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await services.background.cancel_all()
        await ollama.aclose()
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

    for module in (health, projects, runs, providers, conversations, tasks):
        app.include_router(module.router, prefix="/api", dependencies=[Depends(require_token)])
    return app
