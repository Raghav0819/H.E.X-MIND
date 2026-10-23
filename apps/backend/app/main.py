from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import health, projects, providers, runs
from app.auth import require_token
from app.config import Settings, get_settings
from app.db.session import create_engine, create_sessionmaker
from app.providers.ollama import OllamaAdapter
from app.providers.router import ProviderRouter


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)
    sessionmaker = create_sessionmaker(engine)
    ollama = OllamaAdapter(settings.ollama_url, settings.ollama_model)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await ollama.aclose()
        await engine.dispose()

    app = FastAPI(title="H.E.X Mind Backend", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.provider_router = ProviderRouter([ollama], sessionmaker)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    for module in (health, projects, runs, providers):
        app.include_router(module.router, prefix="/api", dependencies=[Depends(require_token)])
    return app
