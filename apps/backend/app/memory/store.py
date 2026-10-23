"""Retrieval memory (plan §6): coding standards and agent self-logs in an embedded ChromaDB.

ChromaDB is for semantic retrieval only; task lifecycle and run state live in PostgreSQL.
Embeddings come from the local Ollama embedding model, so nothing is downloaded or sent out.
Retrieval is best-effort: if it fails, agents work without it and the failure is logged.

Blocking API (Chroma is synchronous); call it from a thread pool in async code.
"""

import hashlib
import logging
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import chromadb
import httpx
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from chromadb.config import Settings as ChromaSettings

logger = logging.getLogger(__name__)

STANDARDS = "coding_standards"
SELF_LOGS = "agent_self_logs"


class OllamaEmbedding(EmbeddingFunction[Documents]):
    def __init__(self, url: str, model: str) -> None:
        self.url = url
        self.model = model

    def __call__(self, input: Documents) -> Embeddings:
        response = httpx.post(
            f"{self.url}/api/embed", json={"model": self.model, "input": list(input)}, timeout=120
        )
        response.raise_for_status()
        return response.json()["embeddings"]

    @staticmethod
    def name() -> str:
        return "hexmind-ollama"

    def get_config(self) -> dict[str, Any]:
        return {"url": self.url, "model": self.model}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "OllamaEmbedding":
        return OllamaEmbedding(config["url"], config["model"])


def chunk_markdown(text: str) -> list[str]:
    """Split a standards document at level-2 headings, keeping the title with each chunk."""
    title_match = re.match(r"#\s+(.+)", text)
    title = title_match.group(1).strip() if title_match else ""
    sections = re.split(r"(?m)^(?=##\s)", text)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section or (
            section.startswith("# ") and "\n##" not in section and len(sections) > 1
        ):
            continue
        chunks.append(f"{title}\n{section}" if title and not section.startswith("# ") else section)
    return chunks


class Memory:
    def __init__(self, path: Path, embedding: EmbeddingFunction[Documents]) -> None:
        self._client = chromadb.PersistentClient(
            path=str(path), settings=ChromaSettings(anonymized_telemetry=False)
        )
        self._embedding = embedding

    def _collection(self, name: str):
        return self._client.get_or_create_collection(name, embedding_function=self._embedding)

    # ---------- coding standards ----------

    def seed_standards(self, docs_dir: Path) -> int:
        """Index docs/standards/*.md; unchanged chunks are skipped, removed ones deleted."""
        collection = self._collection(STANDARDS)
        wanted: dict[str, tuple[str, dict[str, Any]]] = {}
        for doc in sorted(docs_dir.glob("*.md")):
            for i, chunk in enumerate(chunk_markdown(doc.read_text(encoding="utf-8"))):
                digest = hashlib.sha256(chunk.encode()).hexdigest()
                wanted[f"{doc.name}#{i}"] = (chunk, {"source": doc.name, "hash": digest})

        existing = collection.get(include=["metadatas"])
        current = {
            id_: (meta or {}).get("hash")
            for id_, meta in zip(existing["ids"], existing["metadatas"] or [], strict=False)
        }
        stale = [id_ for id_ in current if id_ not in wanted]
        if stale:
            collection.delete(ids=stale)
        changed = [id_ for id_, (_, meta) in wanted.items() if current.get(id_) != meta["hash"]]
        if changed:
            collection.upsert(
                ids=changed,
                documents=[wanted[i][0] for i in changed],
                metadatas=[wanted[i][1] for i in changed],
            )
        return len(changed)

    def standards_for(self, query: str, k: int = 3) -> list[str]:
        return self._query(STANDARDS, query, k)

    # ---------- self-logs ----------

    def add_self_log(
        self, *, run_id: str, task_id: str, role: str, outcome: str, text: str
    ) -> None:
        self._collection(SELF_LOGS).upsert(
            ids=[f"{task_id}:{role}:{outcome}:{hashlib.sha256(text.encode()).hexdigest()[:8]}"],
            documents=[text],
            metadatas=[{"run_id": run_id, "task_id": task_id, "role": role, "outcome": outcome}],
        )

    def self_logs_for(self, query: str, k: int = 2, *, exclude_run: str | None = None) -> list[str]:
        where = {"run_id": {"$ne": exclude_run}} if exclude_run else None
        return self._query(SELF_LOGS, query, k, where=where)

    def _query(self, name: str, query: str, k: int, where: dict | None = None) -> list[str]:
        collection = self._collection(name)
        count = collection.count()
        if count == 0:
            return []
        result = collection.query(query_texts=[query], n_results=min(k, count), where=where)
        return list(result["documents"][0]) if result["documents"] else []


def safely(fn: Callable[..., Sequence[str] | int | None], *args: Any, **kwargs: Any) -> Any:
    """Run a memory operation, degrading to an empty result if retrieval is unavailable."""
    try:
        return fn(*args, **kwargs)
    except Exception:
        logger.warning("memory operation %s failed", getattr(fn, "__name__", fn), exc_info=True)
        return []
