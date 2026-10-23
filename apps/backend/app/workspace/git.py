"""Git operations for safe agent edits (plan §5).

Agents never write to the user's working tree. Each run gets a worktree created from a
snapshot commit of the user's current state; the diff between that snapshot and the worktree
is what the user reviews.

All functions are blocking (plain subprocess) so they work under any asyncio event loop; call
them through a thread pool from async code.
"""

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AUTHOR = ["-c", "user.name=H.E.X Mind", "-c", "user.email=hexmind@localhost"]


class GitError(RuntimeError):
    pass


def _git(
    cwd: Path, *args: str, env: dict[str, str] | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args[:3])} failed: {result.stderr.strip()[:500]}")
    return result


def is_repo(root: Path) -> bool:
    result = _git(root, "rev-parse", "--show-toplevel", check=False)
    return result.returncode == 0 and Path(result.stdout.strip()).resolve() == root.resolve()


def init_repo(root: Path) -> str:
    """Initialize a repository with one commit containing the current files."""
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, *AUTHOR, "commit", "-q", "--allow-empty", "-m", "Initial commit (H.E.X Mind)")
    return head(root)


def head(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def has_commits(root: Path) -> bool:
    return _git(root, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0


def snapshot(root: Path) -> str:
    """Commit object for the user's current working state, including uncommitted and untracked
    (not ignored) files, without touching their index, working tree or branches."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if has_commits(root):
            _git(root, "read-tree", "HEAD", env=env)
        _git(root, "add", "-A", env=env)
        tree = _git(root, "write-tree", env=env).stdout.strip()
    parents = ["-p", head(root)] if has_commits(root) else []
    if parents and tree == _git(root, "rev-parse", "HEAD^{tree}").stdout.strip():
        return head(root)  # clean working tree: the snapshot is HEAD itself
    message = "H.E.X Mind snapshot"
    return _git(root, *AUTHOR, "commit-tree", tree, *parents, "-m", message).stdout.strip()


def create_worktree(root: Path, base: str, path: Path, branch: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(root, "worktree", "add", "-q", "-b", branch, str(path), base)
    return path


def remove_worktree(root: Path, path: Path) -> None:
    _git(root, "worktree", "remove", "--force", str(path), check=False)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    _git(root, "worktree", "prune", check=False)


@dataclass(frozen=True)
class FileDiff:
    path: str
    change_type: Literal["added", "modified", "deleted"]
    diff: str


_STATUS = {"A": "added", "M": "modified", "D": "deleted", "T": "modified"}


def diff(worktree: Path, base: str) -> list[FileDiff]:
    """Changes in the worktree (committed or not, tracked or new) relative to `base`."""
    _git(worktree, "add", "-A")
    names = _git(worktree, "diff", "--cached", "--no-renames", "--name-status", "-z", base).stdout
    fields = [f for f in names.split("\0") if f]
    changes: list[FileDiff] = []
    for status, path in zip(fields[0::2], fields[1::2], strict=True):
        text = _git(worktree, "diff", "--cached", "--no-renames", base, "--", path).stdout
        changes.append(FileDiff(path, _STATUS.get(status[0], "modified"), text))  # type: ignore[arg-type]
    return changes


def show_file(root: Path, commit: str, path: str) -> str | None:
    """File contents at a commit, or None if it does not exist there."""
    result = _git(root, "show", f"{commit}:{path}", check=False)
    return result.stdout if result.returncode == 0 else None
