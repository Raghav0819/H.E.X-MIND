import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.workspace.paths import resolve_in_workspace, to_relative

# Hidden from the explorer entirely.
_HIDDEN_NAMES = frozenset({".git"})

_BINARY_SNIFF_BYTES = 8192


@dataclass(frozen=True)
class TreeEntry:
    name: str
    path: str
    type: Literal["file", "directory"]
    size: int | None


@dataclass(frozen=True)
class FileContent:
    path: str
    content: str | None  # None when the file is binary or too large to edit
    hash: str
    size: int
    binary: bool
    too_large: bool


class FileConflict(Exception):
    """The file on disk no longer matches the version the client edited."""

    def __init__(self, current_hash: str | None) -> None:
        super().__init__("file changed on disk")
        self.current_hash = current_hash


class NotAFile(Exception):
    pass


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def list_directory(root: Path, rel: str = "") -> list[TreeEntry]:
    """Immediate children of a workspace directory, directories first. Symlinks that point
    outside the workspace are omitted."""
    directory = resolve_in_workspace(root, rel)
    if not directory.is_dir():
        raise NotADirectoryError(rel)

    root_real = root.resolve()
    entries: list[TreeEntry] = []
    for child in directory.iterdir():
        if child.name in _HIDDEN_NAMES:
            continue
        real = child.resolve()
        if real != root_real and not real.is_relative_to(root_real):
            continue
        is_dir = real.is_dir()
        entries.append(
            TreeEntry(
                name=child.name,
                path=to_relative(root, directory / child.name),
                type="directory" if is_dir else "file",
                size=None if is_dir else real.stat().st_size,
            )
        )
    entries.sort(key=lambda e: (e.type != "directory", e.name.lower()))
    return entries


def read_file(root: Path, rel: str, *, max_bytes: int) -> FileContent:
    path = resolve_in_workspace(root, rel)
    if not path.is_file():
        raise NotAFile(rel)

    data = path.read_bytes()
    common = {"path": to_relative(root, path), "hash": content_hash(data), "size": len(data)}
    if len(data) > max_bytes:
        return FileContent(content=None, binary=False, too_large=True, **common)
    if b"\x00" in data[:_BINARY_SNIFF_BYTES]:
        return FileContent(content=None, binary=True, too_large=False, **common)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return FileContent(content=None, binary=True, too_large=False, **common)
    return FileContent(content=text, binary=False, too_large=False, **common)


def write_file(root: Path, rel: str, content: str, *, base_hash: str | None) -> str:
    """Write `content` atomically and return the new hash.

    `base_hash` is the hash the client last read: None means "create a new file". If the
    file on disk no longer matches, nothing is written and FileConflict is raised.
    """
    path = resolve_in_workspace(root, rel, for_write=True)
    if path.is_dir():
        raise NotAFile(rel)

    current = content_hash(path.read_bytes()) if path.exists() else None
    if current != base_hash:
        raise FileConflict(current)

    data = content.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return content_hash(data)
