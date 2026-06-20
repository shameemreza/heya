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
import contextlib
import json as _json
import os
import ssl
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

import httpx

from .config import MCPServerConfig
from .tools_files import ToolError


class _Connected:
    def __init__(self, server: MCPServerConfig, session, tools: list, resources: list, prompts: list, stop: asyncio.Event):
        self.server = server
        self.session = session
        self.tools = tools          # list of uniform tool objects (.name/.description/.input_schema)
        self.resources = resources  # list of resource objects captured at connect
        self.prompts = prompts      # list of prompt objects captured at connect
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
        # Keeps pending refresh tasks alive so they can't be GC'd mid-flight.
        self._pending_refreshes: set[asyncio.Task] = set()

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
            on_list_changed = lambda which: self._schedule_refresh(server.name, which)  # noqa: E731
            async with self._open_session(server, env, self._roots_cb(), on_list_changed) as session:
                await session.initialize()
                tools = await self._list_all(session.list_tools, "tools", tolerant=False)
                resources = await self._list_all(session.list_resources, "resources", tolerant=True)
                prompts = await self._list_all(session.list_prompts, "prompts", tolerant=True)
                connected = _Connected(server, session, tools, resources, prompts, stop)
                ready.set_result(connected)
                await stop.wait()
        except asyncio.CancelledError:
            # The connect path cancelled us (timeout). Let cancellation propagate;
            # do not set an exception on `ready` that nobody would retrieve.
            raise
        except BaseException as exc:  # noqa: BLE001
            if not ready.done():
                ready.set_exception(exc if isinstance(exc, Exception) else RuntimeError(str(exc)))

    async def _list_all(self, list_fn, attr, *, tolerant) -> list:
        items, cursor = [], None
        try:
            while True:
                page = await list_fn(cursor)
                items.extend(getattr(page, attr))
                cursor = page.next_cursor
                if not cursor:
                    return items
        except Exception:
            if tolerant:
                return []
            raise

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

    def list_resources(self) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        for conn in self._connected.values():
            for r in conn.resources:
                out.append((conn.server.name, {
                    "uri": getattr(r, "uri", ""),
                    "name": getattr(r, "name", "") or "",
                    "description": getattr(r, "description", "") or "",
                    "mimeType": getattr(r, "mime_type", "") or "",
                }))
        return out

    def list_prompts(self) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        for conn in self._connected.values():
            for p in conn.prompts:
                out.append((conn.server.name, {
                    "name": getattr(p, "name", ""),
                    "description": getattr(p, "description", "") or "",
                    "arguments": [getattr(a, "name", str(a)) for a in (getattr(p, "arguments", None) or [])],
                }))
        return out

    def has_resources(self) -> bool:
        return any(conn.resources for conn in self._connected.values())

    def has_prompts(self) -> bool:
        return any(conn.prompts for conn in self._connected.values())

    def call_tool(self, server: str, tool: str, arguments: dict, *, timeout: float = 120.0) -> str:
        conn = self._connected.get(server)
        if conn is None:
            raise ToolError(f"MCP server {server!r} is not connected")
        try:
            result = self._run(conn.session.call_tool(tool, arguments), timeout=timeout)
        except ToolError:
            raise
        except Exception as exc:  # protocol/transport error or timeout
            raise ToolError(f"MCP call {server}.{tool} failed: {exc}") from exc
        return render_tool_result(result)

    def read_resource(self, server, uri, *, timeout: float = 120.0) -> str:
        conn = self._connected.get(server)
        if conn is None:
            raise ToolError(f"MCP server {server!r} is not connected")
        try:
            contents = self._run(conn.session.read_resource(uri), timeout=timeout)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"MCP read_resource {server}:{uri} failed: {exc}") from exc
        return render_resource(contents)

    def get_prompt(self, server, name, arguments, *, timeout: float = 120.0) -> str:
        conn = self._connected.get(server)
        if conn is None:
            raise ToolError(f"MCP server {server!r} is not connected")
        try:
            result = self._run(conn.session.get_prompt(name, arguments), timeout=timeout)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"MCP get_prompt {server}.{name} failed: {exc}") from exc
        return render_prompt(result)

    # ---- live refresh ---------------------------------------------------------

    async def _refresh(self, server_name, which):
        conn = self._connected.get(server_name)
        if conn is None:
            return
        list_fn = {
            "tools": conn.session.list_tools,
            "resources": conn.session.list_resources,
            "prompts": conn.session.list_prompts,
        }.get(which)
        if list_fn is None:
            return
        try:
            fresh = await self._list_all(list_fn, which, tolerant=False)
        except Exception as exc:  # keep the prior snapshot on failure
            print(f"MCP refresh {which} for {server_name!r} failed: {exc}", file=sys.stderr)
            return
        setattr(conn, which, fresh)  # atomic reference swap

    def trigger_refresh(self, server_name, which) -> None:
        self._run(self._refresh(server_name, which))

    def _schedule_refresh(self, server_name, which) -> None:
        # Called on the loop thread by the real notification handler.
        # Store the task reference to prevent GC mid-flight; discard on completion.
        task = asyncio.ensure_future(self._refresh(server_name, which))
        self._pending_refreshes.add(task)
        task.add_done_callback(self._pending_refreshes.discard)

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
        # Drain any pending refresh tasks so they don't become orphaned/GC'd.
        if self._pending_refreshes:
            await asyncio.gather(*list(self._pending_refreshes), return_exceptions=True)


def build_roots(allowed_roots: Sequence[Path]):
    """The roots/list response: one file:// root per allowed folder.

    Returns a plain list of (uri, name) pairs; the real opener adapts this to the
    SDK's ListRootsResult. Kept SDK-free so it is unit-testable.
    """
    return [(Path(p).resolve().as_uri(), Path(p).name or str(p)) for p in allowed_roots]


def _build_headers(server) -> dict[str, str]:
    """Static headers plus an Authorization: Bearer header from a named env var.

    The token is referenced by env-var NAME and read here; a missing var raises
    ToolError so the server is skipped with a warning (like a missing stdio secret).
    """
    headers = dict(server.headers)
    if server.auth_token_env:
        value = os.environ.get(server.auth_token_env)
        if value is None:
            raise ToolError(f"required env var {server.auth_token_env} is not set")
        headers["Authorization"] = f"Bearer {value}"
    return headers


def _http_client_kwargs(server) -> dict:
    """Pure: the kwargs for the httpx.AsyncClient used by http/sse transports.

    A custom CA and/or a client cert (mTLS) are folded into ONE ssl.SSLContext
    passed as `verify`; no separate `cert=` is ever handed to httpx (httpx
    deprecated that path, and dropping it would silently break mTLS).
    """
    headers = _build_headers(server)
    if server.tls_verify is False:
        return {"headers": headers, "verify": False}
    needs_ctx = bool(server.tls_ca_cert) or bool(server.tls_client_cert and server.tls_client_key)
    if not needs_ctx:
        return {"headers": headers, "verify": True}
    cafile = str(Path(server.tls_ca_cert).expanduser()) if server.tls_ca_cert else None
    ctx = ssl.create_default_context(cafile=cafile)
    if server.tls_client_cert and server.tls_client_key:
        ctx.load_cert_chain(
            str(Path(server.tls_client_cert).expanduser()),
            str(Path(server.tls_client_key).expanduser()),
        )
    return {"headers": headers, "verify": ctx}


def _build_http_client(server) -> httpx.AsyncClient:
    """Construct the auth+TLS httpx client; warn loudly if verification is off."""
    kwargs = _http_client_kwargs(server)
    if kwargs["verify"] is False:
        print(f"MCP server {server.name!r}: TLS verification disabled", file=sys.stderr)
    return httpx.AsyncClient(**kwargs)


def render_tool_result(result) -> str:
    """Render an MCP CallToolResult to a model-visible string.

    Text blocks are joined; non-text blocks become a short placeholder rather
    than being dropped; structuredContent is appended as compact JSON. isError
    does not change rendering — the error content is returned to the model.
    """
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        btype = getattr(block, "type", "")
        if btype == "text":
            parts.append(getattr(block, "text", "") or "")
        elif btype == "image":
            parts.append(f"[image: {getattr(block, 'mime', None) or 'image'}]")
        elif btype in ("resource", "embedded_resource"):
            parts.append(f"[embedded resource: {getattr(block, 'uri', None) or 'resource'}]")
        else:
            parts.append(f"[{btype or 'content'}]")
    structured = getattr(result, "structured_content", None)
    if structured:
        parts.append(_json.dumps(structured))
    return "\n".join(p for p in parts if p) or "(no content)"


def render_resource(contents) -> str:
    """Render an MCP read_resource result (a list of contents) to text.

    Text contents are joined; a binary/blob content (no text) becomes a short
    placeholder rather than being dropped. Empty -> "(empty resource)".
    """
    parts: list[str] = []
    for c in contents or []:
        text = getattr(c, "text", None)
        if text is not None:
            parts.append(text)
        else:
            parts.append(f"[binary resource: {getattr(c, 'mime_type', None) or 'application/octet-stream'}]")
    return "\n".join(p for p in parts if p) or "(empty resource)"


def render_prompt(result) -> str:
    """Render an MCP get_prompt result (description + messages) to text.

    Each message becomes a `role: text` line; non-text message content becomes a
    short placeholder. Empty -> "(empty prompt)".
    """
    parts: list[str] = []
    desc = getattr(result, "description", None)
    if desc:
        parts.append(desc)
    for m in getattr(result, "messages", None) or []:
        role = getattr(m, "role", "?")
        content = getattr(m, "content", None)
        text = getattr(content, "text", None)
        if text is not None:
            parts.append(f"{role}: {text}")
        else:
            parts.append(f"{role}: [{getattr(content, 'type', 'content')}]")
    return "\n".join(parts) or "(empty prompt)"


class _SDKToolsPage:
    def __init__(self, result):
        self.tools = [_SDKTool(t) for t in result.tools]
        # SDK 1.x uses camelCase on the result object
        self.next_cursor = getattr(result, "nextCursor", None)


class _SDKTool:
    def __init__(self, tool):
        self.name = tool.name
        self.description = tool.description or ""
        # inputSchema is always a dict in SDK 1.x (required field)
        self.input_schema = tool.inputSchema or {"type": "object", "properties": {}}


class _SDKResult:
    def __init__(self, result):
        self.content = list(getattr(result, "content", None) or [])
        # SDK 1.x uses camelCase on the result object
        self.is_error = bool(getattr(result, "isError", False))
        self.structured_content = getattr(result, "structuredContent", None)
        # Normalize image block attribute: render_tool_result reads `block.mime`
        # but SDK 1.x ImageContent uses `mimeType`.
        for block in self.content:
            if getattr(block, "type", "") == "image" and not hasattr(block, "mime"):
                block.mime = getattr(block, "mimeType", None)


class _SDKResourcesPage:
    def __init__(self, result):
        self.resources = [_SDKResource(r) for r in result.resources]
        self.next_cursor = getattr(result, "nextCursor", None)


class _SDKResource:
    def __init__(self, r):
        # URI is an AnyUrl on the SDK object; stringify for the uniform interface.
        self.uri = str(r.uri)
        self.name = getattr(r, "name", "") or ""
        self.description = getattr(r, "description", "") or ""
        self.mime_type = getattr(r, "mimeType", "") or ""


class _SDKPromptsPage:
    def __init__(self, result):
        self.prompts = [_SDKPrompt(p) for p in result.prompts]
        self.next_cursor = getattr(result, "nextCursor", None)


class _SDKPrompt:
    def __init__(self, p):
        self.name = p.name
        self.description = getattr(p, "description", "") or ""
        self.arguments = [_SDKPromptArg(a) for a in (getattr(p, "arguments", None) or [])]


class _SDKPromptArg:
    def __init__(self, a):
        self.name = a.name


class _SDKSession:
    """Adapts an mcp.ClientSession to Heya's uniform Session interface."""

    def __init__(self, session):
        self._session = session

    async def initialize(self):
        await self._session.initialize()

    async def list_tools(self, cursor):
        return _SDKToolsPage(await self._session.list_tools(cursor=cursor))

    async def list_resources(self, cursor):
        return _SDKResourcesPage(await self._session.list_resources(cursor=cursor))

    async def list_prompts(self, cursor):
        return _SDKPromptsPage(await self._session.list_prompts(cursor=cursor))

    async def call_tool(self, name, arguments):
        return _SDKResult(await self._session.call_tool(name, arguments or {}))

    async def read_resource(self, uri):
        # SDK 1.x requires AnyUrl, not a plain str.
        from pydantic import AnyUrl
        result = await self._session.read_resource(AnyUrl(uri))
        contents = list(getattr(result, "contents", None) or [])
        # SDK ResourceContents uses camelCase `mimeType`; render_resource reads
        # snake_case `mime_type` on the fallback branch — patch it on each item.
        for c in contents:
            if not hasattr(c, "mime_type"):
                c.mime_type = getattr(c, "mimeType", None)
        return contents

    async def get_prompt(self, name, arguments):
        return await self._session.get_prompt(name, arguments=arguments or {})


@contextlib.asynccontextmanager
async def _default_open_session(server, env, roots_cb, on_list_changed):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import (
        ListRootsResult,
        Root,
        ServerNotification,
        ToolListChangedNotification,
        ResourceListChangedNotification,
        PromptListChangedNotification,
    )

    # SDK 1.x ListRootsFnT signature: async def __call__(self, context) -> ListRootsResult
    async def _list_roots(_context):
        return ListRootsResult(roots=[Root(uri=uri, name=name) for uri, name in roots_cb])

    # message_handler receives RequestResponder | ServerNotification | Exception.
    # ServerNotification is a RootModel; its .root holds the concrete notification.
    async def _message_handler(message):
        if isinstance(message, ServerNotification):
            root = message.root
            if isinstance(root, ToolListChangedNotification):
                on_list_changed("tools")
            elif isinstance(root, ResourceListChangedNotification):
                on_list_changed("resources")
            elif isinstance(root, PromptListChangedNotification):
                on_list_changed("prompts")

    def _wire(read, write):
        return ClientSession(
            read, write,
            list_roots_callback=_list_roots,
            message_handler=_message_handler,
        )

    if server.transport in ("http", "sse"):
        # mcp 1.28.0:
        #   streamable_http_client: accepts http_client=<AsyncClient> directly.
        #   sse_client: accepts httpx_client_factory(headers, timeout, auth) -> AsyncClient.
        # For streamable-http we pass a pre-built client carrying auth+TLS kwargs.
        # For SSE we use a factory that merges SDK-provided base headers onto ours.
        if server.transport == "http":
            from mcp.client.streamable_http import streamable_http_client
            # streamable_http_client only manages the client lifecycle when it
            # creates the client itself; we own ours and must close it.
            http_client = _build_http_client(server)
            try:
                async with streamable_http_client(
                    server.url, http_client=http_client
                ) as (read, write, _get_session_id):
                    async with _wire(read, write) as session:
                        yield _SDKSession(session)
            finally:
                await http_client.aclose()
        else:  # sse
            from mcp.client.sse import sse_client

            def _client_factory(headers=None, timeout=None, auth=None):
                # Merge SDK-provided base headers under ours so auth wins.
                kwargs = _http_client_kwargs(server)
                kwargs["headers"] = {**(headers or {}), **kwargs["headers"]}
                if timeout is not None:
                    kwargs["timeout"] = timeout
                if auth is not None:
                    kwargs["auth"] = auth
                return httpx.AsyncClient(**kwargs)

            async with sse_client(
                server.url, httpx_client_factory=_client_factory
            ) as (read, write):
                async with _wire(read, write) as session:
                    yield _SDKSession(session)
        return

    params = StdioServerParameters(command=server.command, args=list(server.args), env=env)
    async with stdio_client(params) as (read, write):
        async with _wire(read, write) as session:
            yield _SDKSession(session)
