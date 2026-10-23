"""Backend test fixtures.

Database tests run against the `hexmind_test` database from docker-compose (port 5433). The
schema is rebuilt from the Alembic migrations once per session, so the migrations themselves
are exercised, and tables are truncated before each test.
"""

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.config import Settings
from app.db.models import Base
from app.main import create_app
from app.providers.base import Completion, LLMRequest, ProviderHealth
from app.providers.router import ProviderRouter

TOKEN = "test-token-0123456789abcdef"
ORIGIN = "http://localhost:5173"
TEST_DATABASE_URL = os.environ.get(
    "HEXMIND_TEST_DATABASE_URL",
    "postgresql+asyncpg://hexmind:hexmind@127.0.0.1:5433/hexmind_test",
)
BACKEND_DIR = Path(__file__).resolve().parents[1]


async def _reset_schema() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest.fixture(scope="session")
def migrated_database() -> str:
    asyncio.run(_reset_schema())
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = TEST_DATABASE_URL
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
    return TEST_DATABASE_URL


@pytest.fixture
def settings() -> Settings:
    return Settings(
        api_token=TOKEN,
        cors_origins=[ORIGIN],
        database_url=TEST_DATABASE_URL,
        # Nothing listens on the discard port: the real Ollama is never used by default.
        ollama_url="http://127.0.0.1:9",
        _env_file=None,
    )


@pytest.fixture
async def app(migrated_database: str, settings: Settings) -> AsyncIterator[FastAPI]:
    app = create_app(settings)
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with app.state.engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as client:
        yield client


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    # Bytes, not text: write_text would translate "\n" to "\r\n" on Windows.
    (root / "src" / "app.ts").write_bytes(b"export const x = 1\n")
    (root / "README.md").write_bytes(b"# demo\n")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_bytes(b"ref: refs/heads/main\n")
    return root


# ---------- Scripted LLM provider ----------


class ScriptedAdapter:
    """Fake provider: `handler(request)` returns a Completion (or raises ProviderError).
    Every request is recorded for assertions."""

    name = "scripted"
    model = "scripted-model"

    def __init__(self, handler: Callable[[LLMRequest], Completion]) -> None:
        self.handler = handler
        self.requests: list[LLMRequest] = []

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, available=True, model=self.model)

    async def complete(self, request: LLMRequest) -> Completion:
        self.requests.append(request)
        return self.handler(request)


def router_json(**overrides: object) -> str:
    decision = {
        "request_type": "question",
        "complexity": "low",
        "confidence": 0.9,
        "reason": "test",
        "execution_strategy": "direct",
        "requires_planning": False,
        "requires_review": False,
        "clarification_question": None,
    }
    decision.update(overrides)
    return json.dumps(decision)


def scripted(
    router: str | list[str] | None = None, chat: str = "An answer.", summary: str = "Summary."
) -> ScriptedAdapter:
    """Adapter answering by purpose; `router` may be a list of successive raw outputs."""
    router = router_json() if router is None else router
    router_outputs = list(router) if isinstance(router, list) else None

    def handler(request: LLMRequest) -> Completion:
        if request.purpose == "router":
            content = router_outputs.pop(0) if router_outputs is not None else router
            return Completion(content=content, input_tokens=10, output_tokens=5)
        if request.purpose == "summary":
            return Completion(content=summary)
        return Completion(content=chat, input_tokens=100, output_tokens=20)

    return ScriptedAdapter(handler)


def use_adapter(app: FastAPI, adapter: ScriptedAdapter) -> None:
    async def no_sleep(_: float) -> None:
        return None

    router = ProviderRouter([adapter], app.state.sessionmaker, sleep=no_sleep)
    app.state.services.providers = router
    app.state.provider_router = router
