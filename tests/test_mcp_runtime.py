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


class FakeResource:
    def __init__(self, uri, name="", description="", mime_type="text/plain"):
        self.uri = uri
        self.name = name
        self.description = description
        self.mime_type = mime_type


class FakeResourcePage:
    def __init__(self, resources, next_cursor=None):
        self.resources = resources
        self.next_cursor = next_cursor


class FakePromptArg:
    def __init__(self, name):
        self.name = name


class FakePrompt:
    def __init__(self, name, description="", arguments=()):
        self.name = name
        self.description = description
        self.arguments = [FakePromptArg(a) for a in arguments]


class FakePromptPage:
    def __init__(self, prompts, next_cursor=None):
        self.prompts = prompts
        self.next_cursor = next_cursor


class FakeSession:
    """Uniform Session the opener yields. Pages tools to exercise pagination."""
    def __init__(self, pages, *, resource_pages=None, prompt_pages=None, roots_cb=None,
                 supports_resources=True, supports_prompts=True):
        self._pages = pages            # list[FakePage]
        self._resource_pages = resource_pages if resource_pages is not None else [FakeResourcePage([])]
        self._prompt_pages = prompt_pages if prompt_pages is not None else [FakePromptPage([])]
        self._supports_resources = supports_resources
        self._supports_prompts = supports_prompts
        self.initialized = False
        self.roots_cb = roots_cb
        self.closed = False

    async def initialize(self):
        self.initialized = True

    async def list_tools(self, cursor):
        idx = 0 if cursor is None else int(cursor)
        return self._pages[idx]

    async def list_resources(self, cursor):
        if not self._supports_resources:
            raise RuntimeError("Method not found")
        idx = 0 if cursor is None else int(cursor)
        return self._resource_pages[idx]

    async def list_prompts(self, cursor):
        if not self._supports_prompts:
            raise RuntimeError("Method not found")
        idx = 0 if cursor is None else int(cursor)
        return self._prompt_pages[idx]


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


import json
from heya.mcp_runtime import render_tool_result
from heya.tools_files import ToolError


class _Block:
    def __init__(self, type, text=None, uri=None, mime=None):
        self.type = type
        self.text = text
        self.uri = uri
        self.mime = mime


class _Result:
    def __init__(self, content, is_error=False, structured=None):
        self.content = content
        self.is_error = is_error
        self.structured_content = structured


def test_render_joins_text_blocks():
    r = _Result([_Block("text", text="hello"), _Block("text", text="world")])
    assert render_tool_result(r) == "hello\nworld"


def test_render_summarizes_non_text():
    r = _Result([_Block("text", text="ok"), _Block("image", mime="image/png")])
    out = render_tool_result(r)
    assert "ok" in out and "image" in out


def test_render_includes_structured_content():
    r = _Result([], structured={"count": 3})
    assert json.dumps({"count": 3}) in render_tool_result(r)


def test_render_tolerates_empty():
    assert render_tool_result(_Result([])) == "(no content)"


# --- call_tool via a fake session that records calls ---

class CallSession(FakeSession):
    def __init__(self, pages, **kw):
        super().__init__(pages, **kw)
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "boom":
            raise RuntimeError("protocol failure")
        if name == "toolerr":
            return _Result([_Block("text", text="bad input")], is_error=True)
        return _Result([_Block("text", text=f"ran {name} {arguments}")])


def _call_opener(pages):
    import contextlib
    @contextlib.asynccontextmanager
    async def opener(server, env, roots_cb):
        yield CallSession(pages[server.name], roots_cb=roots_cb)
    return opener


def test_call_tool_success():
    pages = {"demo": [FakePage([FakeTool("greet")])]}
    rt = MCPRuntime([cfg("demo")], open_session=_call_opener(pages))
    rt.connect_all()
    try:
        out = rt.call_tool("demo", "greet", {"x": 1})
        assert "ran greet" in out and "'x': 1" in out
    finally:
        rt.close()


def test_call_tool_tool_error_is_returned_not_raised():
    pages = {"demo": [FakePage([FakeTool("toolerr")])]}
    rt = MCPRuntime([cfg("demo")], open_session=_call_opener(pages))
    rt.connect_all()
    try:
        out = rt.call_tool("demo", "toolerr", {})
        assert "bad input" in out  # model-visible, no raise
    finally:
        rt.close()


def test_call_tool_protocol_error_raises_toolerror():
    pages = {"demo": [FakePage([FakeTool("boom")])]}
    rt = MCPRuntime([cfg("demo")], open_session=_call_opener(pages))
    rt.connect_all()
    try:
        with pytest.raises(ToolError):
            rt.call_tool("demo", "boom", {})
    finally:
        rt.close()


def test_call_tool_unknown_server_raises():
    rt = MCPRuntime([], open_session=_call_opener({}))
    rt.connect_all()
    try:
        with pytest.raises(ToolError):
            rt.call_tool("nope", "x", {})
    finally:
        rt.close()


# --- resources and prompts capture tests ---

def _res_opener(pages, resource_pages=None, prompt_pages=None, **kw):
    import contextlib
    @contextlib.asynccontextmanager
    async def opener(server, env, roots_cb):
        yield FakeSession(pages, resource_pages=resource_pages, prompt_pages=prompt_pages,
                          roots_cb=roots_cb, **kw)
    return opener


def test_resources_and_prompts_captured_at_connect():
    rt = MCPRuntime([cfg("demo")], open_session=_res_opener(
        [FakePage([FakeTool("t")])],
        resource_pages=[FakeResourcePage([FakeResource("file:///a", "A")])],
        prompt_pages=[FakePromptPage([FakePrompt("p", "desc", ("x",))])],
    ))
    rt.connect_all()
    try:
        assert rt.has_resources() is True
        assert rt.has_prompts() is True
        (srv, res), = rt.list_resources()
        assert srv == "demo" and res["uri"] == "file:///a" and res["name"] == "A"
        (psrv, pr), = rt.list_prompts()
        assert psrv == "demo" and pr["name"] == "p" and pr["arguments"] == ["x"]
    finally:
        rt.close()


def test_resource_pagination_collects_all_pages():
    rt = MCPRuntime([cfg("demo")], open_session=_res_opener(
        [FakePage([FakeTool("t")])],
        resource_pages=[
            FakeResourcePage([FakeResource("file:///a")], next_cursor="1"),
            FakeResourcePage([FakeResource("file:///b")], next_cursor=None),
        ],
    ))
    rt.connect_all()
    try:
        uris = sorted(r["uri"] for _, r in rt.list_resources())
        assert uris == ["file:///a", "file:///b"]
    finally:
        rt.close()


def test_capability_absence_is_tolerant():
    # A server that does not support resources/prompts captures empty, connect still succeeds.
    rt = MCPRuntime([cfg("demo")], open_session=_res_opener(
        [FakePage([FakeTool("t")])],
        supports_resources=False, supports_prompts=False,
    ))
    rt.connect_all()
    try:
        assert rt.has_resources() is False
        assert rt.has_prompts() is False
        assert rt.list_resources() == []
        assert rt.list_prompts() == []
        # the server is still connected — its tool is present
        assert [s["name"] for _, s in rt.list_tools()] == ["t"]
    finally:
        rt.close()
