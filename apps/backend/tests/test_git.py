import subprocess
from pathlib import Path

import pytest

from app.workspace import git


def _status(root: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.ts").write_bytes(b"export const x = 1\n")
    (root / ".gitignore").write_bytes(b"node_modules/\n")
    git.init_repo(root)
    return root


def test_init_repo_commits_existing_files(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.txt").write_bytes(b"a")
    assert not git.is_repo(root)
    git.init_repo(root)
    assert git.is_repo(root)
    assert git.show_file(root, "HEAD", "a.txt") == "a"
    assert _status(root) == ""


def test_snapshot_of_clean_tree_is_head(repo: Path) -> None:
    assert git.snapshot(repo) == git.head(repo)


def test_snapshot_includes_uncommitted_work_without_touching_it(repo: Path) -> None:
    (repo / "src" / "app.ts").write_bytes(b"export const x = 2\n")  # modified
    (repo / "notes.md").write_bytes(b"draft\n")  # untracked
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "big.js").write_bytes(b"ignored\n")
    before = _status(repo)
    head = git.head(repo)

    base = git.snapshot(repo)

    assert base != head
    assert git.show_file(repo, base, "src/app.ts") == "export const x = 2\n"
    assert git.show_file(repo, base, "notes.md") == "draft\n"
    assert git.show_file(repo, base, "node_modules/big.js") is None  # .gitignore respected
    assert _status(repo) == before  # index and working tree untouched
    assert git.head(repo) == head  # branch not moved


def test_worktree_isolates_agent_edits_and_diffs_against_base(repo: Path, tmp_path: Path) -> None:
    (repo / "notes.md").write_bytes(b"draft\n")
    base = git.snapshot(repo)
    worktree = git.create_worktree(repo, base, tmp_path / "wt" / "run1", "hexmind/run-1")

    (worktree / "src" / "app.ts").write_bytes(b"export const x = 3\n")
    (worktree / "src" / "new.ts").write_bytes(b"export {}\n")
    (worktree / "notes.md").unlink()

    changes = {c.path: c for c in git.diff(worktree, base)}
    assert {p: c.change_type for p, c in changes.items()} == {
        "src/app.ts": "modified",
        "src/new.ts": "added",
        "notes.md": "deleted",
    }
    assert "+export const x = 3" in changes["src/app.ts"].diff
    # The user's files are untouched.
    assert (repo / "src" / "app.ts").read_bytes() == b"export const x = 1\n"
    assert (repo / "notes.md").exists()

    git.remove_worktree(repo, worktree)
    assert not worktree.exists()
    # The run branch is kept for history.
    branches = subprocess.run(
        ["git", "branch", "--list", "hexmind/*"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "hexmind/run-1" in branches


def test_snapshot_works_in_repo_without_commits(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "a.txt").write_bytes(b"a")
    base = git.snapshot(root)
    assert git.show_file(root, base, "a.txt") == "a"
