"""CrewAI tools backed by the MCP workspace server. Each call is reported through `on_call` so the
run gets `tool_called` events."""

from collections.abc import Callable
from typing import Any

from crewai.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from app.agents.mcp_bridge import McpWorkspace

MAX_TOOL_OUTPUT = 8000

READ_ONLY = ("list_files", "read_file", "search_code")
REVIEW = (*READ_ONLY, "run_check")
CODER = (*READ_ONLY, "write_file", "replace_in_file", "run_check")

ToolListener = Callable[[str, dict[str, Any], bool, str], None]


class _Path(BaseModel):
    path: str = Field(description="Workspace-relative file path, e.g. src/app.js")


class _OptionalPath(BaseModel):
    path: str = Field(default="", description="Optional directory to list; empty for all files")


class _Query(BaseModel):
    query: str = Field(description="Text to search for (case-insensitive)")


class _Write(BaseModel):
    path: str = Field(description="Workspace-relative file path")
    content: str = Field(description="The complete new file content")


class _Replace(BaseModel):
    path: str = Field(description="Workspace-relative file path")
    old: str = Field(description="Exact existing text; must occur exactly once")
    new: str = Field(description="Replacement text")


class _Check(BaseModel):
    name: str = Field(description="Check name from the project profile, usually 'test'")


SPECS: dict[str, tuple[type[BaseModel], str]] = {
    "list_files": (_OptionalPath, "List workspace files, one relative path per line."),
    "read_file": (_Path, "Read the current content of a workspace file."),
    "search_code": (_Query, "Search all workspace files; returns path:line: text matches."),
    "write_file": (_Write, "Create or overwrite a file with its complete new content."),
    "replace_in_file": (_Replace, "Replace one exact, unique snippet in a file."),
    "run_check": (_Check, "Run a project check such as 'test' in the sandbox; returns JSON."),
}


class McpTool(BaseTool):
    _workspace: McpWorkspace = PrivateAttr()
    _listener: ToolListener | None = PrivateAttr(default=None)

    def _run(self, **kwargs: Any) -> str:
        ok, text = self._workspace.call_tool(self.name, kwargs)
        if self._listener:
            self._listener(self.name, kwargs, ok, text)
        if len(text) > MAX_TOOL_OUTPUT:
            text = text[:MAX_TOOL_OUTPUT] + "\n… (output truncated)"
        return text


def make_tools(
    workspace: McpWorkspace, names: tuple[str, ...], listener: ToolListener | None = None
) -> list[BaseTool]:
    tools: list[BaseTool] = []
    for name in names:
        schema, description = SPECS[name]
        tool = McpTool(name=name, description=description, args_schema=schema)
        tool._workspace = workspace
        tool._listener = listener
        tools.append(tool)
    return tools
