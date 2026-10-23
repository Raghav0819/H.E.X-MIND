"""Workspace path guard: the single place that turns a client-supplied relative path into a
filesystem path. Every file operation must go through `resolve_in_workspace`.
"""

from pathlib import Path, PurePosixPath, PureWindowsPath

# Windows device names are reserved regardless of extension (e.g. "nul.txt").
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

# Never writable through the editor API, even inside the workspace.
_WRITE_PROTECTED_DIRS = frozenset({".git"})


class PathViolation(ValueError):
    """The requested path is invalid or escapes the workspace."""


def normalize_relative(rel: str) -> PurePosixPath:
    """Validate a workspace-relative path and return it in POSIX form ("" means the root)."""
    if "\x00" in rel:
        raise PathViolation("path contains a NUL byte")
    win = PureWindowsPath(rel)
    if win.drive or win.root or rel.startswith(("/", "\\")):
        raise PathViolation("path must be relative to the workspace")

    parts: list[str] = []
    for part in rel.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise PathViolation("path must not contain '..'")
        if ":" in part:
            raise PathViolation("path must not contain ':' (drive or alternate data stream)")
        if part != part.rstrip(" ."):
            raise PathViolation("path segments must not end with a space or dot")
        if part.split(".")[0].upper() in _RESERVED_NAMES:
            raise PathViolation(f"'{part}' is a reserved device name")
        parts.append(part)
    return PurePosixPath(*parts)


def resolve_in_workspace(root: Path, rel: str, *, for_write: bool = False) -> Path:
    """Resolve `rel` under `root`, following symlinks, and reject anything outside it."""
    normalized = normalize_relative(rel)
    if for_write and any(part.lower() in _WRITE_PROTECTED_DIRS for part in normalized.parts):
        raise PathViolation(f"'{normalized}' is write-protected")

    root_real = root.resolve(strict=True)
    candidate = (root_real.joinpath(*normalized.parts)).resolve(strict=False)
    if candidate != root_real and not candidate.is_relative_to(root_real):
        raise PathViolation("path resolves outside the workspace")
    return candidate


def to_relative(root: Path, path: Path) -> str:
    """POSIX-style path of `path` relative to the resolved workspace root."""
    return path.relative_to(root.resolve()).as_posix()
