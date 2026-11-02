import os
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/backend/app/config.py -> repository root
ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_DATA_DIR = (
    Path(os.environ["LOCALAPPDATA"]) / "hexmind"
    if os.name == "nt" and "LOCALAPPDATA" in os.environ
    else Path.home() / ".local" / "share" / "hexmind"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HEXMIND_", env_file=ROOT_ENV_FILE, extra="ignore")

    api_token: str = Field(min_length=16)
    host: str = "127.0.0.1"
    port: int = 8765
    cors_origins: list[str] = ["http://localhost:5173"]

    database_url: str = "postgresql+asyncpg://hexmind:hexmind@127.0.0.1:5433/hexmind"

    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5-coder:7b"
    # Ollama's default context window is small; prompts carry project context.
    ollama_num_ctx: int = 8192
    # Local generation of a long answer can take minutes on modest hardware.
    ollama_timeout_s: float = 600

    # Hosted providers (OpenAI-compatible APIs). A provider without a key is not used.
    groq_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("HEXMIND_GROQ_API_KEY", "GROQ_API_KEY")
    )
    groq_model: str = "openai/gpt-oss-120b"
    gemini_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("HEXMIND_GEMINI_API_KEY", "GEMINI_API_KEY")
    )
    gemini_model: str = "gemini-3.5-flash"

    # Provider selection policy: tried in this order, skipping unconfigured or unavailable
    # providers. Optional per-complexity orders ({"low": ["ollama", ...]}) override it.
    provider_order: list[str] = ["groq", "gemini", "ollama"]
    provider_order_by_complexity: dict[str, list[str]] = {}
    # How long a provider is skipped after quota exhaustion (unless it sends Retry-After).
    quota_cooldown_s: float = 300
    # Agents use native (structured) tool calls; False falls back to CrewAI's text ReAct.
    native_tool_calling: bool = True

    # Approximate token budget for the context bundle sent with chat/router prompts.
    context_budget_tokens: int = 5000
    # Below this Router confidence, Auto mode asks for clarification instead of editing.
    router_min_confidence: float = 0.6

    # Files larger than this are not opened in the editor.
    max_editor_file_bytes: int = 2 * 1024 * 1024

    # App-owned state outside any workspace: run worktrees, vector store, CrewAI storage.
    data_dir: Path = DEFAULT_DATA_DIR

    # Worker swarm.
    worker_concurrency: int = 2
    # Workers renew their task lease every quarter lease while they work on it.
    task_lease_s: int = 600
    agent_max_iterations: int = 15
    review_max_rounds: int = 2
    # When every provider fails for the Reviewer, retry the review after these pauses (seconds)
    # before giving up: an outage is not a verdict.
    review_retry_delays_s: list[float] = [20.0, 60.0]

    # Sandbox for checks. Only these images may be used, whatever a project profile says.
    sandbox_images: list[str] = ["node:22-alpine", "python:3.11-slim"]
    sandbox_timeout_s: int = 120

    # OpenTelemetry: OTLP/HTTP traces endpoint, e.g. http://127.0.0.1:4318/v1/traces.
    otlp_endpoint: str | None = None

    # RAG store (ChromaDB). Embeddings come from the local Ollama.
    memory_enabled: bool = True
    embedding_model: str = "nomic-embed-text"
    standards_dir: Path = REPO_ROOT / "docs" / "standards"

    @field_validator("host")
    @classmethod
    def host_must_be_loopback(cls, value: str) -> str:
        if value != "localhost" and not ip_address(value).is_loopback:
            raise ValueError("backend must bind to a loopback address")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # api_token comes from the environment
