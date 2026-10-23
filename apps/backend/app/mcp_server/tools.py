"""Workspace tools exposed to agents over MCP. Pure functions over one worktree root, so they
are testable without the MCP transport.

Every path goes through the workspace path guard with the agent policy: no escapes, no
`.git`/`.hexmind`/`node_modules`, no `.env*`. Commands are never accepted: `run_check` takes a
check *name* defined by the project profile.
"""

import json
from dataclasses import asdict
from pathlib import Path

from app.context import workspace_scan as scan
from app.sandbox.profile import load_profile
from app.sandbox.runner import run_check as sandbox_run_check
from app.workspace.paths import resolve_in_workspace

MAX_READ_BYTES = 100 * 1024
MAX_WRITE_BYTES = 200 * 1024
MAX_SEARCH_HITS = 50


class ToolError(ValueError):
    """An error the agent should see and can recover from."""


class WorkspaceTools:
    def __init__(
        self, root: Path, *, workspace: Path, allowed_images: list[str], check_timeout_s: int
    ) -> None:
        self.root = root.resolve()
        self.workspace = workspace
        self.allowed_images = allowed_images
        self.check_timeout_s = check_timeout_s

    def _path(self, rel: str, *, write: bool = False) -> Path:
        try:
            return resolve_in_workspace(self.root, rel, for_write=write, agent=True)
        except ValueError as exc:
            raise ToolError(str(exc)) from None

    def list_files(self, path: str = "") -> str:
        prefix = self._path(path).relative_to(self.root).as_posix() if path else ""
        files = [
            f.path
            for f in scan.list_files(self.root)
            if not prefix or f.path == prefix or f.path.startswith(prefix + "/")
        ]
        return "\n".join(files) if files else "(no files)"

    def read_file(self, path: str) -> str:
        target = self._path(path)
        if not target.is_file():
            raise ToolError(f"{path} does not exist")
        if target.stat().st_size > MAX_READ_BYTES:
            raise ToolError(f"{path} is larger than {MAX_READ_BYTES // 1024} KB")
        text = scan.read_text(self.root, target.relative_to(self.root).as_posix())
        if text is None:
            raise ToolError(f"{path} is not a UTF-8 text file")
        return text

    def search_code(self, query: str) -> str:
        if len(query.strip()) < 2:
            raise ToolError("query must be at least 2 characters")
        needle = query.lower()
        hits: list[str] = []
        for file in scan.list_files(self.root):
            text = scan.read_text(self.root, file.path)
            if text is None:
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if needle in line.lower():
                    hits.append(f"{file.path}:{number}: {line.strip()[:200]}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        return "\n".join(hits) + "\n… (more results omitted)"
        return "\n".join(hits) if hits else "(no matches)"

    def write_file(self, path: str, content: str) -> str:
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            raise ToolError(f"content is larger than {MAX_WRITE_BYTES // 1024} KB")
        target = self._path(path, write=True)
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return f"{'updated' if existed else 'created'} {path} ({len(data)} bytes)"

    def replace_in_file(self, path: str, old: str, new: str) -> str:
        target = self._path(path, write=True)
        text = self.read_file(path)
        count = text.count(old)
        if count != 1:
            raise ToolError(f"`old` must occur exactly once in {path}; found {count} times")
        target.write_bytes(text.replace(old, new).encode("utf-8"))
        return f"updated {path}"

    def run_check(self, name: str) -> str:
        """Run a named profile check in the sandbox; returns a JSON result."""
        try:
            profile = load_profile(self.workspace, self.root, self.allowed_images)
            command = profile.command(name)
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        outcome = sandbox_run_check(
            name=name,
            command=command,
            image=profile.image,
            worktree=self.root,
            timeout_s=self.check_timeout_s,
        )
        return json.dumps(asdict(outcome))
