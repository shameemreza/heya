import contextlib
from pathlib import Path

import pytest

from heya.config import MCPServerConfig
from heya.mcp_runtime import MCPRuntime


class FakeTool:
    def __init__(self, name, description="", input_schema=None):
        self.name = name
        self.description = description
        self.input_schema = input_schema or {"type": "object", "properties": {}}


class FakePage:
    def __init__(self, tools, next_cursor=None):
        self.tools = tools
        self.next_cursor = next_cursor


class FakeSession:
    """Uniform Session the opener yields. Pages tools to exercise pagination."""
    def __init__(self, pages, *, roots_cb=None):
        self._pages = pages            # list[FakePage]
        self.initialized = False
        self.roots_cb = roots_cb
        self.closed = False

    async def initialize(self):
        self.initialized = True

    async def list_tools(self, cursor):
        idx = 0 if cursor is None else int(cursor)
        return self._pages[idx]


def make_opener(pages_by_server, *, fail=(), hang=()):
    """Build a fake open_session seam. `fail`: server names that raise on open.
    `hang`: server names whose open sleeps forever (to test connect_timeout."""
    import asyncio

    @contextlib.asynccontextmanager
    async def opener(server, env, roots_cb):
        if server.name in hang:
            await asyncio.Event().wait()  # never returns
        if server.name in fail:
            raise RuntimeError("boom")
        yield FakeSession(pages_by_server[server.name], roots_cb=roots_cb)

    return opener


def cfg(name, **kw):
    return MCPServerConfig(name=name, command="x", **kw)


def test_connect_and_list_tools_single_page():
    pages = {"demo": [FakePage([FakeTool("alpha"), FakeTool("beta")])]}
    rt = MCPRuntime([cfg("demo")], open_session=make_opener(pages))
    rt.connect_all()
    try:
        names = sorted(s["name"] for _, s in rt.list_tools())
        assert names == ["alpha", "beta"]
        servers = {srv for srv, _ in rt.list_tools()}
        assert servers == {"demo"}
    finally:
        rt.close()


def test_pagination_collects_all_pages():
    pages = {"demo": [
        FakePage([FakeTool("a")], next_cursor="1"),
        FakePage([FakeTool("b")], next_cursor="2"),
        FakePage([FakeTool("c")], next_cursor=None),
    ]}
    rt = MCPRuntime([cfg("demo")], open_session=make_opener(pages))
    rt.connect_all()
    try:
        assert sorted(s["name"] for _, s in rt.list_tools()) == ["a", "b", "c"]
    finally:
        rt.close()


def test_curation_filters_tools():
    pages = {"demo": [FakePage([FakeTool("keep"), FakeTool("drop")])]}
    rt = MCPRuntime([cfg("demo", tools=("keep",))], open_session=make_opener(pages))
    rt.connect_all()
    try:
        assert [s["name"] for _, s in rt.list_tools()] == ["keep"]
    finally:
        rt.close()


def test_disabled_server_not_connected():
    pages = {"demo": [FakePage([FakeTool("a")])]}
    rt = MCPRuntime([cfg("demo", enabled=False)], open_session=make_opener(pages))
    rt.connect_all()
    try:
        assert rt.list_tools() == []
    finally:
        rt.close()


def test_failed_server_is_skipped_with_warning(capsys):
    pages = {"ok": [FakePage([FakeTool("a")])]}
    rt = MCPRuntime([cfg("ok"), cfg("bad")],
                    open_session=make_opener(pages, fail=("bad",)))
    rt.connect_all()
    try:
        assert [s["name"] for _, s in rt.list_tools()] == ["a"]
        assert "bad" in capsys.readouterr().err
    finally:
        rt.close()


def test_missing_secret_skips_server(capsys, monkeypatch):
    monkeypatch.delenv("ABSENT_TOKEN", raising=False)
    pages = {"demo": [FakePage([FakeTool("a")])]}
    rt = MCPRuntime([cfg("demo", env_keys=("ABSENT_TOKEN",))],
                    open_session=make_opener(pages))
    rt.connect_all()
    try:
        assert rt.list_tools() == []
        assert "ABSENT_TOKEN" in capsys.readouterr().err
    finally:
        rt.close()


def test_connect_timeout_skips_hanging_server(capsys):
    pages = {"ok": [FakePage([FakeTool("a")])]}
    rt = MCPRuntime([cfg("ok"), cfg("slow")], connect_timeout=0.2,
                    open_session=make_opener(pages, hang=("slow",)))
    rt.connect_all()
    try:
        assert [s["name"] for _, s in rt.list_tools()] == ["a"]
        assert "slow" in capsys.readouterr().err
    finally:
        rt.close()


def test_close_is_idempotent():
    pages = {"demo": [FakePage([FakeTool("a")])]}
    rt = MCPRuntime([cfg("demo")], open_session=make_opener(pages))
    rt.connect_all()
    rt.close()
    rt.close()  # must not raise
