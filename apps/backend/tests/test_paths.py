import os
from pathlib import Path

import pytest

from app.workspace.paths import PathViolation, normalize_relative, resolve_in_workspace


@pytest.mark.parametrize(
    "rel",
    [
        "../secret.txt",
        "src/../../secret.txt",
        "src/..",
        "..\\secret.txt",
        "/etc/passwd",
        "\\Windows\\win.ini",
        "C:\\Windows\\win.ini",
        "C:/Windows/win.ini",
        "C:relative.txt",
        "\\\\server\\share\\file.txt",
        "//server/share/file.txt",
        "src/app.ts:hidden",  # NTFS alternate data stream
        "a\x00b",
        "nul",
        "NUL.txt",
        "src/con",
        "com1.log",
        "LPT9",
        "src./app.ts",  # Windows strips trailing dots -> aliasing
        "src /app.ts",
        "app.ts.",
    ],
)
def test_rejects_unsafe_paths(tmp_path: Path, rel: str) -> None:
    with pytest.raises(PathViolation):
        resolve_in_workspace(tmp_path, rel)


@pytest.mark.parametrize(
    ("rel", "expected"),
    [
        ("", ""),
        (".", ""),
        ("src/app.ts", "src/app.ts"),
        ("src\\app.ts", "src/app.ts"),
        ("./src//app.ts", "src/app.ts"),
        ("console.ts", "console.ts"),  # only exact device names are reserved
        (".env", ".env"),
    ],
)
def test_accepts_safe_paths(tmp_path: Path, rel: str, expected: str) -> None:
    assert normalize_relative(rel).as_posix() in (expected, ".")
    resolved = resolve_in_workspace(tmp_path, rel)
    assert resolved == tmp_path.resolve().joinpath(*normalize_relative(rel).parts)


@pytest.mark.parametrize("rel", [".git/config", ".GIT/hooks/pre-commit", "sub/.git/HEAD"])
def test_git_directory_is_write_protected(tmp_path: Path, rel: str) -> None:
    resolve_in_workspace(tmp_path, rel)  # readable
    with pytest.raises(PathViolation):
        resolve_in_workspace(tmp_path, rel, for_write=True)


def _symlink_or_skip(link: Path, target: Path, *, directory: bool) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this system (enable Windows Developer Mode)")


def test_rejects_symlink_escaping_workspace(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    _symlink_or_skip(root / "link", outside, directory=True)

    with pytest.raises(PathViolation):
        resolve_in_workspace(root, "link/secret.txt")


def test_allows_symlink_within_workspace(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    _symlink_or_skip(tmp_path / "alias", tmp_path / "real", directory=True)
    assert resolve_in_workspace(tmp_path, "alias/file.txt") == (
        tmp_path.resolve() / "real" / "file.txt"
    )
