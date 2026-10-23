"""Read-only workspace inspection for building model context."""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from app.context.redact import is_secret_file

IGNORED_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "dist",
        "build",
        "out",
        ".next",
        "coverage",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".hexmind",
        ".idea",
        ".vscode",
    }
)

MAX_TEXT_FILE_BYTES = 200 * 1024


@dataclass(frozen=True)
class WorkspaceFile:
    path: str  # POSIX, relative to the workspace root
    size: int


def list_files(root: Path, *, max_files: int = 3000) -> list[WorkspaceFile]:
    """Workspace files, skipping ignored directories, secret files and symlinks."""
    root = root.resolve()
    files: list[WorkspaceFile] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for name in sorted(filenames):
            full = Path(dirpath) / name
            if full.is_symlink():
                continue
            rel = full.relative_to(root).as_posix()
            if is_secret_file(rel):
                continue
            files.append(WorkspaceFile(path=rel, size=full.stat().st_size))
            if len(files) >= max_files:
                return files
    return files


def read_text(root: Path, rel: str) -> str | None:
    """UTF-8 contents of a small text file, or None for binary/large/unreadable files."""
    path = root / rel
    try:
        if path.stat().st_size > MAX_TEXT_FILE_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def render_tree(files: list[WorkspaceFile], *, max_depth: int = 3, max_lines: int = 150) -> str:
    """Indented tree of directories and files, trimmed by depth and line count."""
    lines: list[str] = []
    seen_dirs: set[str] = set()
    for file in files:
        parts = file.path.split("/")
        for depth in range(1, min(len(parts), max_depth + 1)):
            directory = "/".join(parts[:depth])
            if directory not in seen_dirs:
                seen_dirs.add(directory)
                lines.append(f"{'  ' * (depth - 1)}{parts[depth - 1]}/")
        if len(parts) <= max_depth:
            lines.append(f"{'  ' * (len(parts) - 1)}{parts[-1]}")
    if len(lines) > max_lines:
        return "\n".join(lines[:max_lines]) + f"\n… ({len(lines) - max_lines} more entries)"
    return "\n".join(lines)


def detect_stack(root: Path, files: list[WorkspaceFile]) -> list[str]:
    """Coarse technology hints from well-known manifest files."""
    paths = {f.path for f in files}
    stack: list[str] = []
    if "package.json" in paths:
        stack.append("node")
        try:
            manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
            deps = {**manifest.get("dependencies", {}), **manifest.get("devDependencies", {})}
            for name in ("react", "vue", "svelte", "next", "vite", "express", "electron"):
                if name in deps:
                    stack.append(name)
            if "typescript" in deps:
                stack.append("typescript")
        except (OSError, ValueError):
            pass
    if "tsconfig.json" in paths and "typescript" not in stack:
        stack.append("typescript")
    if paths & {"pyproject.toml", "requirements.txt", "setup.py"}:
        stack.append("python")
    if "go.mod" in paths:
        stack.append("go")
    if "Cargo.toml" in paths:
        stack.append("rust")
    return stack


_PATH_TOKEN = re.compile(r"[\w./\\-]+\.[A-Za-z0-9]{1,8}\b")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
_STOPWORDS = frozenset(
    """this that with from have what when where which there their them they then than
    into onto your about would could should make makes made does done just like
    file files code change changes please using used page add remove update create
    explain show tell need want also some more less""".split()
)


def mentioned_files(message: str, files: list[WorkspaceFile]) -> list[str]:
    """Workspace files referenced in a message by relative path or unique basename."""
    by_path = {f.path.lower(): f.path for f in files}
    by_name: dict[str, list[str]] = {}
    for f in files:
        by_name.setdefault(f.path.rsplit("/", 1)[-1].lower(), []).append(f.path)

    found: list[str] = []
    for token in _PATH_TOKEN.findall(message):
        key = token.replace("\\", "/").strip("./").lower()
        match = by_path.get(key) or (by_name[key][0] if len(by_name.get(key, [])) == 1 else None)
        if match and match not in found:
            found.append(match)
    return found


def keywords(message: str) -> list[str]:
    words = []
    for word in _WORD.findall(message):
        lowered = word.lower()
        if lowered not in _STOPWORDS and lowered not in words:
            words.append(lowered)
    return words[:12]


def search_files(
    root: Path, files: list[WorkspaceFile], terms: list[str], *, limit: int = 3
) -> list[str]:
    """Files ranked by how many distinct search terms (then total hits) they contain."""
    if not terms:
        return []
    scored: list[tuple[int, int, str]] = []
    for file in files:
        if file.size > MAX_TEXT_FILE_BYTES:
            continue
        text = read_text(root, file.path)
        if text is None:
            continue
        lowered = text.lower()
        counts = [lowered.count(term) for term in terms]
        distinct = sum(1 for c in counts if c)
        if distinct:
            scored.append((distinct, sum(counts), file.path))
    scored.sort(key=lambda s: (-s[0], -s[1], s[2]))
    return [path for _, _, path in scored[:limit]]
