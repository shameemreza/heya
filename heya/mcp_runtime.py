"""Synchronous owner of MCP server sessions over a single asyncio loop-thread.

The official MCP SDK is asyncio-only; Heya's loop is synchronous. One daemon
thread runs one event loop for Heya's lifetime; every server session lives on
it, each inside its own long-running task that holds the stdio connection open.
Sync callers submit coroutines with run_coroutine_threadsafe(...).result(). The
rest of Heya sees only sync methods, exactly as BrowserSession/ProcessRegistry
hide their internals.

A server that fails to connect (spawn error, handshake timeout, or a missing
named secret) is skipped with a one-line stderr warning; Heya always reaches
the REPL.
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from .config import MCPServerConfig
from .tools_files import ToolError


class _Connected:
    def __init__(self, server: MCPServerConfig, session, tools: list, stop: asyncio.Event):
        self.server = server
        self.session = session
        self.tools = tools          # list of uniform tool objects (.name/.description/.input_schema)
        self.stop = stop


class MCPRuntime:
    def __init__(
        self,
        servers: Sequence[MCPServerConfig],
        *,
        allowed_roots: Sequence[Path] = (),
        connect_timeout: float = 10.0,
        open_session=None,
    ) -> None:
        self._servers = list(servers)
        self._allowed_roots = [Path(p) for p in allowed_roots]
        self._connect_timeout = connect_timeout
        self._open_session = open_session or _default_open_session
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._connected: dict[str, _Connected] = {}
        self._closed = False

    # ---- loop-thread plumbing -------------------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, name="mcp-runtime", daemon=True)
        thread.start()
        self._loop, self._thread = loop, thread
        return loop

    def _run(self, coro, *, timeout: float | None = None):
        loop = self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)

    # ---- env / roots ----------------------------------------------------------

    def _build_env(self, server: MCPServerConfig) -> dict[str, str]:
        env = dict(os.environ)
        for name in server.env_keys:
            value = os.environ.get(name)
            if value is None:
                raise ToolError(f"required env var {name} is not set")
            env[name] = value
        return env

    def _roots_cb(self):
        return build_roots(self._allowed_roots)

    # ---- connect --------------------------------------------------------------

    def connect_all(self) -> None:
        self._ensure_loop()
        enabled = [s for s in self._servers if s.enabled]
        if not enabled:
            return
        results = self._run(self._connect_many(enabled))
        for server, outcome in zip(enabled, results):
            if isinstance(outcome, _Connected):
                self._connected[server.name] = outcome
            else:
                print(f"MCP server {server.name!r} unavailable: {outcome}", file=sys.stderr)

    async def _connect_many(self, servers):
        return await asyncio.gather(*(self._connect_one(s) for s in servers))

    async def _connect_one(self, server: MCPServerConfig):
        try:
            env = self._build_env(server)  # missing secret raises here
        except ToolError as exc:
            return str(exc)
        ready: asyncio.Future = asyncio.get_running_loop().create_future()
        stop = asyncio.Event()
        # The session task owns the connection's whole lifecycle (open -> wait -> close)
        # in ONE task, so anyio cancel scopes inside the SDK stay valid.
        task = asyncio.ensure_future(self._serve(server, env, ready, stop))
        try:
            connected = await asyncio.wait_for(asyncio.shield(ready), self._connect_timeout)
        except asyncio.TimeoutError:
            stop.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return "connect timed out"
        except Exception as exc:  # noqa: BLE001 - any failure => skip
            stop.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return str(exc)
        connected.stop = stop
        connected._task = task  # keep a reference so it isn't GC'd
        return connected

    async def _serve(self, server, env, ready: asyncio.Future, stop: asyncio.Event):
        try:
            async with self._open_session(server, env, self._roots_cb()) as session:
                await session.initialize()
                tools = await self._list_all_tools(session)
                connected = _Connected(server, session, tools, stop)
                ready.set_result(connected)
                await stop.wait()
        except asyncio.CancelledError:
            # The connect path cancelled us (timeout). Let cancellation propagate;
            # do not set an exception on `ready` that nobody would retrieve.
            raise
        except BaseException as exc:  # noqa: BLE001
            if not ready.done():
                ready.set_exception(exc if isinstance(exc, Exception) else RuntimeError(str(exc)))

    async def _list_all_tools(self, session) -> list:
        tools, cursor = [], None
        while True:
            page = await session.list_tools(cursor)
            tools.extend(page.tools)
            cursor = page.next_cursor
            if not cursor:
                return tools

    # ---- accessors ------------------------------------------------------------

    def list_tools(self) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        for conn in self._connected.values():
            allow = conn.server.tools
            for tool in conn.tools:
                if "*" in allow or tool.name in allow:
                    out.append((conn.server.name, {
                        "name": tool.name,
                        "description": tool.description or "",
                        "inputSchema": tool.input_schema or {"type": "object", "properties": {}},
                    }))
        return out

    # ---- teardown -------------------------------------------------------------

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        loop = self._loop
        if loop is None:
            return
        try:
            self._run(self._shutdown(), timeout=10.0)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        # The thread has exited run_forever, so the loop is idle and safe to close.
        loop.close()
        self._connected.clear()
        self._loop = self._thread = None

    async def _shutdown(self):
        tasks = []
        for conn in self._connected.values():
            conn.stop.set()
            task = getattr(conn, "_task", None)
            if task is not None:
                tasks.append(task)
        # Let each _serve task finish exiting its async-with before the loop stops.
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def build_roots(allowed_roots: Sequence[Path]):
    """The roots/list response: one file:// root per allowed folder.

    Returns a plain list of (uri, name) pairs; the real opener adapts this to the
    SDK's ListRootsResult. Kept SDK-free so it is unit-testable.
    """
    return [(Path(p).resolve().as_uri(), Path(p).name or str(p)) for p in allowed_roots]


async def _default_open_session(server, env, roots_cb):  # replaced in Task 5
    raise ToolError("the mcp SDK opener is not installed yet")
