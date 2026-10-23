"""Client side of the MCP workspace server.

The MCP stdio client runs on its own thread with its own event loop (a Proactor loop on
Windows), because the server event loop may not support subprocesses (uvicorn --reload on
Windows uses a selector loop) and because CrewAI calls tools from worker threads anyway.
`call_tool` is synchronous and thread-safe.
"""

import asyncio
import os
import re
import sys
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BACKEND_DIR = Path(__file__).resolve().parents[2]
_SECRET_ENV = re.compile(r"(TOKEN|KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.IGNORECASE)


def _server_env() -> dict[str, str]:
    """The tool server needs PATH/Docker settings but none of our secrets."""
    return {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}


class McpWorkspace:
    def __init__(
        self,
        *,
        root: Path,
        workspace: Path,
        allowed_images: list[str],
        check_timeout_s: int,
        call_timeout_s: float = 300,
    ) -> None:
        self._params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m", "app.mcp_server",
                "--root", str(root),
                "--workspace", str(workspace),
                "--allowed-images", ",".join(allowed_images),
                "--check-timeout", str(check_timeout_s),
            ],
            cwd=str(BACKEND_DIR),
            env=_server_env(),
        )  # fmt: skip
        self._call_timeout_s = call_timeout_s
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session: ClientSession | None = None
        self._stop: asyncio.Event | None = None
        self._ready: Future[list[str]] = Future()
        self._thread: threading.Thread | None = None

    def start(self, timeout_s: float = 60) -> list[str]:
        """Start the server; returns the names of the tools it offers."""
        self._thread = threading.Thread(target=self._run, name="mcp-workspace", daemon=True)
        self._thread.start()
        return self._ready.result(timeout=timeout_s)

    def _run(self) -> None:
        loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
        self._loop = loop
        try:
            loop.run_until_complete(self._serve())
        except BaseException as exc:  # surface startup failures to start()
            if not self._ready.done():
                self._ready.set_exception(exc)
        finally:
            loop.close()

    async def _serve(self) -> None:
        self._stop = asyncio.Event()
        async with stdio_client(self._params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                self._session = session
                self._ready.set_result([t.name for t in tools.tools])
                await self._stop.wait()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        """Call a tool; returns (ok, text). Tool-level errors come back as ok=False."""
        if self._loop is None or self._session is None:
            raise RuntimeError("MCP workspace is not started")
        session = self._session
        future = asyncio.run_coroutine_threadsafe(session.call_tool(name, arguments), self._loop)
        result = future.result(timeout=self._call_timeout_s)
        text = "\n".join(getattr(block, "text", "") for block in result.content)
        ok = not result.isError and not text.startswith("ERROR:")
        return ok, text

    def close(self) -> None:
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread is not None:
            self._thread.join(timeout=15)

    def __enter__(self) -> "McpWorkspace":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
