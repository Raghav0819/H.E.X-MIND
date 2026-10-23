from pathlib import Path

import pytest

from app.workspace import files


def test_list_directory_sorts_dirs_first_and_hides_git(workspace: Path) -> None:
    (workspace / "a.txt").write_text("a")
    entries = files.list_directory(workspace)
    assert [(e.name, e.type) for e in entries] == [
        ("src", "directory"),
        ("a.txt", "file"),
        ("README.md", "file"),
    ]
    assert files.list_directory(workspace, "src")[0].path == "src/app.ts"


def test_list_directory_rejects_files(workspace: Path) -> None:
    with pytest.raises(NotADirectoryError):
        files.list_directory(workspace, "README.md")


def test_read_text_file(workspace: Path) -> None:
    content = files.read_file(workspace, "src/app.ts", max_bytes=1024)
    assert content.content == "export const x = 1\n"
    assert content.hash == files.content_hash(b"export const x = 1\n")
    assert not content.binary and not content.too_large


def test_read_binary_and_large_files_return_no_content(workspace: Path) -> None:
    (workspace / "image.png").write_bytes(b"\x89PNG\x00\x01")
    (workspace / "latin1.txt").write_bytes("caf\xe9".encode("latin-1"))
    (workspace / "big.txt").write_text("x" * 2000)

    assert files.read_file(workspace, "image.png", max_bytes=1024).binary
    assert files.read_file(workspace, "latin1.txt", max_bytes=1024).binary
    big = files.read_file(workspace, "big.txt", max_bytes=1024)
    assert big.too_large and big.content is None and big.size == 2000


def test_write_creates_and_updates_with_matching_hash(workspace: Path) -> None:
    created = files.write_file(workspace, "src/new/file.ts", "one", base_hash=None)
    assert (workspace / "src/new/file.ts").read_text() == "one"

    updated = files.write_file(workspace, "src/new/file.ts", "two", base_hash=created)
    assert (workspace / "src/new/file.ts").read_text() == "two"
    assert updated == files.content_hash(b"two")


def test_write_detects_stale_base_hash(workspace: Path) -> None:
    original = files.read_file(workspace, "src/app.ts", max_bytes=1024)
    (workspace / "src/app.ts").write_text("changed outside the editor")

    with pytest.raises(files.FileConflict) as exc:
        files.write_file(workspace, "src/app.ts", "mine", base_hash=original.hash)
    assert exc.value.current_hash == files.content_hash(b"changed outside the editor")
    assert (workspace / "src/app.ts").read_text() == "changed outside the editor"


def test_create_conflicts_when_file_already_exists(workspace: Path) -> None:
    with pytest.raises(files.FileConflict):
        files.write_file(workspace, "README.md", "overwrite", base_hash=None)


def test_write_leaves_no_temp_files(workspace: Path) -> None:
    files.write_file(workspace, "notes.txt", "hello", base_hash=None)
    assert sorted(p.name for p in workspace.iterdir() if p.name.endswith(".tmp")) == []
