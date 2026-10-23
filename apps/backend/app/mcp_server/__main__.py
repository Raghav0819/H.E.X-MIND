"""MCP workspace server (stdio). Started by the backend once per run, bound to the run's worktree.

    python -m app.mcp_server --root <worktree> --workspace <user workspace> \
        --allowed-images node:22-alpine,python:3.11-slim --check-timeout 120
"""

import argparse
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from app.mcp_server.tools import ToolError, WorkspaceTools


def build_server(tools: WorkspaceTools) -> FastMCP:
    server = FastMCP("hexmind-workspace")

    def guarded(fn):
        def call(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except ToolError as exc:
                return f"ERROR: {exc}"

        call.__name__ = fn.__name__
        call.__doc__ = fn.__doc__
        return call

    @server.tool()
    def list_files(path: str = "") -> str:
        """List workspace files (optionally under a directory), one relative path per line."""
        return guarded(tools.list_files)(path)

    @server.tool()
    def read_file(path: str) -> str:
        """Read a UTF-8 text file from the workspace."""
        return guarded(tools.read_file)(path)

    @server.tool()
    def search_code(query: str) -> str:
        """Case-insensitive text search across workspace files; returns path:line: text."""
        return guarded(tools.search_code)(query)

    @server.tool()
    def write_file(path: str, content: str) -> str:
        """Create or overwrite a file with the full new content."""
        return guarded(tools.write_file)(path, content)

    @server.tool()
    def replace_in_file(path: str, old: str, new: str) -> str:
        """Replace one exact, unique occurrence of `old` with `new` in a file."""
        return guarded(tools.replace_in_file)(path, old, new)

    @server.tool()
    def run_check(name: str) -> str:
        """Run a named project check (for example `test`) in the sandbox; returns JSON."""
        return guarded(tools.run_check)(name)

    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--allowed-images", required=True)
    parser.add_argument("--check-timeout", type=int, default=120)
    args = parser.parse_args()
    tools = WorkspaceTools(
        args.root,
        workspace=args.workspace,
        allowed_images=args.allowed_images.split(","),
        check_timeout_s=args.check_timeout,
    )
    build_server(tools).run("stdio")


if __name__ == "__main__":
    main()
