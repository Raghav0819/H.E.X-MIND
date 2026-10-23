import hashlib
import math
from pathlib import Path

import pytest
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from app.memory.store import Memory, OllamaEmbedding, chunk_markdown, safely

STANDARDS_DIR = Path(__file__).resolve().parents[3] / "docs" / "standards"


class BagOfWords(EmbeddingFunction[Documents]):
    """Deterministic offline embedding for tests: hashed word counts."""

    def __init__(self) -> None:
        pass

    def __call__(self, input: Documents) -> Embeddings:
        vectors = []
        for text in input:
            vector = [0.0] * 64
            for word in text.lower().split():
                vector[int(hashlib.md5(word.strip(".,:;`()").encode()).hexdigest(), 16) % 64] += 1
            norm = math.sqrt(sum(v * v for v in vector)) or 1.0
            vectors.append([v / norm for v in vector])
        return vectors

    @staticmethod
    def name() -> str:
        return "test-bow"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict) -> "BagOfWords":
        return BagOfWords()


@pytest.fixture
def memory(tmp_path: Path) -> Memory:
    return Memory(tmp_path / "chroma", BagOfWords())


def test_chunk_markdown_keeps_title_per_section() -> None:
    chunks = chunk_markdown(
        "# Testing\n\nIntro\n\n## Node tests\nUse node:test.\n\n## Style\nOne.\n"
    )
    assert chunks == ["Testing\n## Node tests\nUse node:test.", "Testing\n## Style\nOne."]


def test_seed_standards_is_incremental(memory: Memory, tmp_path: Path) -> None:
    docs = tmp_path / "standards"
    docs.mkdir()
    (docs / "a.md").write_text("# A\n## One\nfirst\n## Two\nsecond\n", encoding="utf-8")
    assert memory.seed_standards(docs) == 2
    assert memory.seed_standards(docs) == 0  # unchanged

    (docs / "a.md").write_text("# A\n## One\nfirst, edited\n", encoding="utf-8")
    assert memory.seed_standards(docs) == 1
    assert memory.standards_for("first edited", k=5) == ["A\n## One\nfirst, edited"]


def _ollama_embedding() -> OllamaEmbedding:
    embedding = OllamaEmbedding("http://127.0.0.1:11434", "nomic-embed-text")
    try:
        embedding(["probe"])
    except Exception as exc:
        pytest.skip(f"Ollama embeddings unavailable: {exc}")
    return embedding


def test_repository_standards_are_retrievable(tmp_path: Path) -> None:
    """Real embeddings: retrieval quality is what matters here, so no fake."""
    memory = Memory(tmp_path / "chroma", _ollama_embedding())
    assert memory.seed_standards(STANDARDS_DIR) > 5
    hits = memory.standards_for("how should I write node tests with node:test", k=2)
    assert any("node:test" in hit for hit in hits)


def test_self_logs_exclude_current_run(memory: Memory) -> None:
    memory.add_self_log(
        run_id="r1", task_id="t1", role="coder", outcome="failed",
        text="Tests failed because localStorage is undefined in node; keep storage separate.",
    )  # fmt: skip
    memory.add_self_log(run_id="r2", task_id="t2", role="coder", outcome="completed", text="ok")
    assert "localStorage" in memory.self_logs_for("localStorage tests fail", k=1)[0]
    assert memory.self_logs_for("localStorage", k=5, exclude_run="r1") == ["ok"]


def test_empty_collections_and_failures_degrade(memory: Memory) -> None:
    assert memory.standards_for("anything") == []

    def broken() -> list[str]:
        raise ConnectionError("ollama down")

    assert safely(broken) == []
