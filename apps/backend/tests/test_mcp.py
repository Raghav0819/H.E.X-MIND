import json
from pathlib import Path

import pytest

from app.agents.mcp_bridge import McpWorkspace
from app.mcp_server.tools import ToolError, WorkspaceTools

ALLOWED = ["node:22-alpine"]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path / "wt"
    for rel, data in {
        "src/todo.js": b"export function add(list, title) {\n  return [...list, title]\n}\n",
        "README.md": b"# demo\n",
        ".env": b"SECRET=1\n",
        ".hexmind/profile.yaml": b"image: node:22-alpine\nchecks:\n  test: node --test\n",
        "node_modules/x/index.js": b"x\n",
    }.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    (tmp_path / "outside.txt").write_bytes(b"secret")
    return root


@pytest.fixture
def tools(root: Path, tmp_path: Path) -> WorkspaceTools:
    return WorkspaceTools(
        root, workspace=tmp_path / "ws", allowed_images=ALLOWED, check_timeout_s=60
    )


def test_list_read_search(tools: WorkspaceTools) -> None:
    listing = tools.list_files()
    assert "src/todo.js" in listing and ".env" not in listing and "node_modules" not in listing
    assert tools.list_files("src") == "src/todo.js"
    assert "return [...list, title]" in tools.read_file("src/todo.js")
    assert tools.search_code("ADD(") == "src/todo.js:1: export function add(list, title) {"


@pytest.mark.parametrize(
    "path",
    ["../outside.txt", "C:/Windows/win.ini", ".env", "config/.env.local", ".hexmind/profile.yaml",
     "node_modules/x/index.js", ".git/config"],
)  # fmt: skip
def test_agents_cannot_reach_protected_paths(tools: WorkspaceTools, path: str) -> None:
    with pytest.raises(ToolError):
        tools.read_file(path)
    with pytest.raises(ToolError):
        tools.write_file(path, "x")


def test_write_and_replace(tools: WorkspaceTools, root: Path) -> None:
    assert tools.write_file("src/new.js", "export const a = 1\n") == "created src/new.js (19 bytes)"
    tools.replace_in_file("src/new.js", "a = 1", "a = 2")
    assert (root / "src/new.js").read_text() == "export const a = 2\n"
    with pytest.raises(ToolError, match="exactly once"):
        tools.replace_in_file("src/new.js", "missing", "x")


def test_run_check_rejects_unknown_names(tools: WorkspaceTools) -> None:
    with pytest.raises(ToolError, match="unknown check 'rm -rf /'"):
        tools.run_check("rm -rf /")


def test_stdio_server_round_trip(root: Path, tmp_path: Path) -> None:
    """The real MCP server subprocess, through the threaded client bridge."""
    workspace = McpWorkspace(
        root=root, workspace=tmp_path / "ws", allowed_images=ALLOWED, check_timeout_s=60
    )
    names = workspace.start()
    try:
        assert set(names) == {
            "list_files", "read_file", "search_code", "write_file", "replace_in_file", "run_check",
        }  # fmt: skip
        ok, text = workspace.call_tool("read_file", {"path": "src/todo.js"})
        assert ok and "export function add" in text
        ok, text = workspace.call_tool("read_file", {"path": "../outside.txt"})
        assert not ok and text.startswith("ERROR:")
        ok, _ = workspace.call_tool("write_file", {"path": "src/b.js", "content": "b\n"})
        assert ok and (root / "src/b.js").read_text() == "b\n"
        ok, text = workspace.call_tool("run_check", {"name": "deploy"})
        assert not ok and "unknown check" in text
    finally:
        workspace.close()


def test_run_check_returns_structured_result(tools: WorkspaceTools, root: Path) -> None:
    from app.sandbox.runner import docker_available

    if not docker_available()[0]:
        pytest.skip("Docker unavailable")
    (root / "add.test.js").write_bytes(b"require('node:test')('ok', () => {})\n")
    result = json.loads(tools.run_check("test"))
    assert result["name"] == "test" and result["exit_code"] == 0
