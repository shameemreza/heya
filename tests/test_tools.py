import json
from pathlib import Path

import pytest

from heya.tools import TOOL_SCHEMAS, build_tool_schemas, dispatch_tool, describe_call
from heya.tools_mcp import _MAX_DESC  # noqa: F401  (referenced for the truncation test)


class FakeMCPRuntime:
    def __init__(self, tools, *, result="MCP_OK"):
        self._tools = tools          # list[(server, {"name","description","inputSchema"})]
        self._result = result
        self.calls = []

    def list_tools(self):
        return self._tools

    def has_resources(self):
        return False

    def has_prompts(self):
        return False

    def call_tool(self, server, tool, arguments, *, timeout=120.0):
        self.calls.append((server, tool, arguments))
        return self._result


def test_build_tool_schemas_none_matches_static():
    assert build_tool_schemas(None) == TOOL_SCHEMAS


def test_build_tool_schemas_appends_namespaced_mcp_tools():
    rt = FakeMCPRuntime([("linear", {
        "name": "create_issue", "description": "Make an issue",
        "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}}},
    })])
    schemas = build_tool_schemas(rt)
    assert schemas[:len(TOOL_SCHEMAS)] == TOOL_SCHEMAS
    extra = schemas[len(TOOL_SCHEMAS):]
    assert len(extra) == 1
    fn = extra[0]["function"]
    assert fn["name"] == "mcp__linear__create_issue"
    assert fn["parameters"] == {"type": "object", "properties": {"title": {"type": "string"}}}


def test_build_tool_schemas_truncates_long_description():
    rt = FakeMCPRuntime([("s", {
        "name": "t", "description": "x" * 5000, "inputSchema": {"type": "object"},
    })])
    desc = build_tool_schemas(rt)[len(TOOL_SCHEMAS):][0]["function"]["description"]
    assert len(desc) <= 1024


def test_dispatch_routes_mcp_call_to_runtime():
    rt = FakeMCPRuntime([("linear", {"name": "create_issue", "description": "", "inputSchema": {}})])
    out = dispatch_tool(
        "mcp__linear__create_issue", '{"title": "Bug"}',
        allowed_roots=[], cwd=Path("."), timeout=10, mcp_runtime=rt,
    )
    assert out == "MCP_OK"
    assert rt.calls == [("linear", "create_issue", {"title": "Bug"})]


def test_dispatch_unknown_mcp_tool_errors():
    rt = FakeMCPRuntime([])
    out = dispatch_tool(
        "mcp__nope__nope", "{}", allowed_roots=[], cwd=Path("."), timeout=10, mcp_runtime=rt,
    )
    assert out.startswith("Error")


def test_dispatch_mcp_without_runtime_errors():
    out = dispatch_tool("mcp__x__y", "{}", allowed_roots=[], cwd=Path("."), timeout=10)
    assert out.startswith("Error")


def test_describe_call_renders_mcp():
    assert describe_call("mcp__linear__create_issue", '{"title": "Bug"}') == "mcp__linear__create_issue → linear.create_issue({'title': 'Bug'})"


def test_schemas_cover_the_three_tools():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert {"read_file", "write_file", "run_command"} <= names
    for s in TOOL_SCHEMAS:
        assert s["type"] == "function"
        assert "parameters" in s["function"]


def test_dispatch_read_file_returns_content(tmp_path):
    (tmp_path / "a.txt").write_text("hi")
    out = dispatch_tool(
        "read_file",
        json.dumps({"path": str(tmp_path / "a.txt")}),
        allowed_roots=[tmp_path],
        cwd=tmp_path,
        timeout=10,
    )
    assert out == "hi"


def test_dispatch_write_file_creates_and_reports(tmp_path):
    out = dispatch_tool(
        "write_file",
        json.dumps({"path": str(tmp_path / "out.txt"), "content": "data"}),
        allowed_roots=[tmp_path],
        cwd=tmp_path,
        timeout=10,
    )
    assert (tmp_path / "out.txt").read_text() == "data"
    assert "4" in out  # reports bytes written


def test_dispatch_run_command_returns_output(tmp_path):
    out = dispatch_tool(
        "run_command",
        json.dumps({"cmd": "echo hi"}),
        allowed_roots=[tmp_path],
        cwd=tmp_path,
        timeout=10,
    )
    assert "hi" in out


def test_dispatch_read_file_is_truncated(tmp_path):
    big = "z" * 40000
    (tmp_path / "big.txt").write_text(big)
    out = dispatch_tool(
        "read_file", json.dumps({"path": str(tmp_path / "big.txt")}),
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10,
    )
    assert len(out) < len(big)
    assert "truncated" in out


def test_dispatch_tool_error_becomes_string(tmp_path):
    out = dispatch_tool(
        "read_file",
        json.dumps({"path": "/etc/passwd"}),
        allowed_roots=[tmp_path],
        cwd=tmp_path,
        timeout=10,
    )
    assert "Error" in out and "outside" in out


def test_dispatch_bad_json_becomes_string(tmp_path):
    out = dispatch_tool("read_file", "{not json", allowed_roots=[tmp_path], cwd=tmp_path, timeout=10)
    assert "Error" in out


def test_dispatch_unknown_tool_becomes_string(tmp_path):
    out = dispatch_tool("nope", "{}", allowed_roots=[tmp_path], cwd=tmp_path, timeout=10)
    assert "Error" in out and "nope" in out


def test_dispatch_non_dict_json_becomes_string(tmp_path):
    # Valid JSON that isn't an object must not raise — the loop must keep going.
    for arguments in ("123", "[1, 2, 3]", '"hi"', "null"):
        out = dispatch_tool("read_file", arguments, allowed_roots=[tmp_path], cwd=tmp_path, timeout=10)
        assert "Error" in out


def test_describe_call_summarizes_write(tmp_path):
    summary = describe_call("write_file", json.dumps({"path": "out.txt", "content": "x"}))
    assert "write_file" in summary and "out.txt" in summary


def test_schemas_include_read_guidance():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert "read_guidance" in names


def test_dispatch_read_guidance_lists(tmp_path):
    skill = tmp_path / "voice"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: voice\ndescription: how to write\n---\nbody\n")
    out = dispatch_tool(
        "read_guidance", "{}",
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10, guidance_sources=[tmp_path],
    )
    assert "voice" in out and "how to write" in out


def test_dispatch_read_guidance_reads_named(tmp_path):
    skill = tmp_path / "voice"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: voice\ndescription: d\n---\nTHE VOICE RULES\n")
    out = dispatch_tool(
        "read_guidance", json.dumps({"name": "voice"}),
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10, guidance_sources=[tmp_path],
    )
    assert "THE VOICE RULES" in out


def test_describe_call_summarizes_read_guidance():
    assert "read_guidance" in describe_call("read_guidance", json.dumps({"name": "voice"}))


class _FakeProvider:
    def search(self, query, max_results=5):
        from heya.tools_web import SearchResult
        return [SearchResult(title="Fake", url="https://fake", snippet=f"about {query}")]


def test_schemas_include_web_tools():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert {"web_search", "web_fetch"} <= names


def test_dispatch_web_search_uses_provider(tmp_path):
    out = dispatch_tool(
        "web_search", json.dumps({"query": "pytest"}),
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10, search_provider=_FakeProvider(),
    )
    assert "Fake" in out and "https://fake" in out and "about pytest" in out


def test_dispatch_web_search_without_provider_errors(tmp_path):
    out = dispatch_tool(
        "web_search", json.dumps({"query": "x"}),
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10,
    )
    assert "Error" in out


def test_dispatch_web_search_clamps_max_results_to_at_least_one(tmp_path):
    class _Recorder:
        seen = None

        def search(self, query, max_results=5):
            _Recorder.seen = max_results
            from heya.tools_web import SearchResult
            return [SearchResult(title="t", url="https://u", snippet="s")]

    rec = _Recorder()
    dispatch_tool(
        "web_search", json.dumps({"query": "x", "max_results": 0}),
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10, search_provider=rec,
    )
    assert _Recorder.seen == 1  # 0 clamped up to 1


def test_dispatch_web_fetch_routes(tmp_path, monkeypatch):
    monkeypatch.setattr("heya.tools.web_fetch", lambda url, *, timeout: f"FETCHED {url}")
    out = dispatch_tool(
        "web_fetch", json.dumps({"url": "https://example.com"}),
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10,
    )
    assert "FETCHED https://example.com" in out


def test_describe_call_web_tools():
    assert "web_search" in describe_call("web_search", json.dumps({"query": "q"}))
    assert "web_fetch" in describe_call("web_fetch", json.dumps({"url": "https://x"}))


class _FakeSession:
    def __init__(self):
        self.calls = []

    def navigate(self, url):
        self.calls.append(("navigate", url)); return f"NAV {url}"

    def snapshot(self):
        self.calls.append(("snapshot",)); return "SNAP"

    def click(self, target):
        self.calls.append(("click", target)); return f"CLICK {target}"

    def type_text(self, target, text):
        self.calls.append(("type", target, text)); return f"TYPE {target}={text}"

    def screenshot(self, path):
        self.calls.append(("screenshot", path)); return f"SHOT {path}"

    def evidence(self):
        self.calls.append(("evidence",)); return "EVIDENCE"


def test_schemas_include_browser_tools():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert {"browser_navigate", "browser_snapshot", "browser_click",
            "browser_type", "browser_screenshot", "browser_evidence"} <= names


def test_dispatch_browser_navigate(tmp_path):
    s = _FakeSession()
    out = dispatch_tool("browser_navigate", json.dumps({"url": "https://x"}),
                        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10, browser_session=s)
    assert out == "NAV https://x"


def test_dispatch_browser_click_and_type(tmp_path):
    s = _FakeSession()
    assert "CLICK Go" in dispatch_tool("browser_click", json.dumps({"target": "Go"}),
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10, browser_session=s)
    assert "TYPE Email=a@b" in dispatch_tool("browser_type", json.dumps({"target": "Email", "text": "a@b"}),
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10, browser_session=s)


def test_dispatch_browser_screenshot_uses_allowlist(tmp_path):
    s = _FakeSession()
    out = dispatch_tool("browser_screenshot", json.dumps({"path": str(tmp_path / "a.png")}),
                        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10, browser_session=s)
    assert "SHOT" in out and "a.png" in out


def test_dispatch_browser_screenshot_denies_outside_allowlist(tmp_path):
    s = _FakeSession()
    out = dispatch_tool("browser_screenshot", json.dumps({"path": "/etc/evil.png"}),
                        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10, browser_session=s)
    assert "Error" in out


def test_dispatch_browser_without_session_errors(tmp_path):
    out = dispatch_tool("browser_navigate", json.dumps({"url": "https://x"}),
                        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10)
    assert "Error" in out


def test_describe_call_browser_tools():
    assert "browser_navigate" in describe_call("browser_navigate", json.dumps({"url": "https://x"}))
    assert "browser_click" in describe_call("browser_click", json.dumps({"target": "Go"}))


class _FakeRegistry:
    def __init__(self):
        self.started = []
        self.killed = []

    def start(self, cmd, *, cwd):
        self.started.append((cmd, cwd))
        from heya.process import ManagedProcess
        return ManagedProcess(id="p1", pid=4242)

    def poll(self, id):
        return f"[{id} running]\nsome output"

    def kill(self, id):
        self.killed.append(id)
        return f"Killed background process {id}."


def test_run_command_background_starts_and_returns_handle(tmp_path):
    reg = _FakeRegistry()
    out = dispatch_tool(
        "run_command", json.dumps({"cmd": "npm run dev", "background": True}),
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10, process_registry=reg,
    )
    assert "p1" in out and "4242" in out
    assert reg.started and reg.started[0][0] == "npm run dev"


def test_check_command_polls_registry(tmp_path):
    reg = _FakeRegistry()
    out = dispatch_tool(
        "check_command", json.dumps({"id": "p1"}),
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10, process_registry=reg,
    )
    assert "some output" in out


def test_kill_command_kills_registry(tmp_path):
    reg = _FakeRegistry()
    out = dispatch_tool(
        "kill_command", json.dumps({"id": "p1"}),
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10, process_registry=reg,
    )
    assert "Killed" in out and reg.killed == ["p1"]


def test_background_tools_without_registry_error(tmp_path):
    out = dispatch_tool(
        "check_command", json.dumps({"id": "p1"}),
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10,
    )
    assert "Error" in out


def test_dispatch_read_log_routes(tmp_path):
    (tmp_path / "wp-content").mkdir()
    (tmp_path / "wp-content" / "debug.log").write_text("PHP Fatal error: boom\n")
    out = dispatch_tool(
        "read_log", json.dumps({"path": str(tmp_path), "grep": "Fatal"}),
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10, wp_default_root=None,
    )
    assert "boom" in out


def test_schemas_include_read_log():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert "read_log" in names


def test_dispatch_run_wp_cli_routes(tmp_path, monkeypatch):
    import heya.tools_wp as wp_mod
    monkeypatch.setattr(wp_mod.shutil, "which", lambda _: "/usr/bin/wp")
    monkeypatch.setattr(wp_mod, "run_command", lambda cmd, **k: __import__("heya.tools_files", fromlist=["CommandResult"]).CommandResult(stdout=cmd, stderr="", exit_code=0))
    out = dispatch_tool(
        "run_wp_cli", json.dumps({"args": "plugin list", "path": str(tmp_path)}),
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10,
    )
    assert "plugin list" in out


def test_describe_run_wp_cli_shows_command():
    assert "wp plugin list" in describe_call("run_wp_cli", json.dumps({"args": "plugin list"}))


class _FakePlayground:
    def __init__(self):
        self.calls = []

    def start(self, blueprint=None):
        self.calls.append(("start", blueprint)); return "URL http://127.0.0.1:9400"

    def stop(self):
        self.calls.append(("stop",)); return "stopped"


def test_dispatch_wp_playground_start_and_stop(tmp_path):
    pg = _FakePlayground()
    out = dispatch_tool("wp_playground", json.dumps({"action": "start"}),
                        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10, playground_session=pg)
    assert "9400" in out
    out2 = dispatch_tool("wp_playground", json.dumps({"action": "stop"}),
                         allowed_roots=[tmp_path], cwd=tmp_path, timeout=10, playground_session=pg)
    assert "stopped" in out2


def test_dispatch_wp_playground_without_session_errors(tmp_path):
    out = dispatch_tool("wp_playground", json.dumps({"action": "start"}),
                        allowed_roots=[tmp_path], cwd=tmp_path, timeout=10)
    assert "Error" in out


class FakeMCPRuntime2:
    def __init__(self, *, resources=(), prompts=()):
        self._resources = list(resources)   # list[(server, dict)]
        self._prompts = list(prompts)
        self.reads = []
        self.gets = []

    def list_tools(self):
        return []

    def has_resources(self):
        return bool(self._resources)

    def has_prompts(self):
        return bool(self._prompts)

    def list_resources(self):
        return self._resources

    def list_prompts(self):
        return self._prompts

    def read_resource(self, server, uri, *, timeout=120.0):
        self.reads.append((server, uri))
        return f"RES:{server}:{uri}"

    def get_prompt(self, server, name, arguments, *, timeout=120.0):
        self.gets.append((server, name, arguments))
        return f"PROMPT:{server}:{name}:{arguments}"


def _names(schemas):
    return [s["function"]["name"] for s in schemas]


def test_resource_tools_appear_only_with_resources():
    rt = FakeMCPRuntime2(resources=[("linear", {"uri": "u", "name": "n", "description": "d", "mimeType": "text/plain"})])
    names = _names(build_tool_schemas(rt))
    assert "mcp_list_resources" in names and "mcp_read_resource" in names
    assert "mcp_list_prompts" not in names and "mcp_get_prompt" not in names


def test_prompt_tools_appear_only_with_prompts():
    rt = FakeMCPRuntime2(prompts=[("linear", {"name": "p", "description": "d", "arguments": ["x"]})])
    names = _names(build_tool_schemas(rt))
    assert "mcp_list_prompts" in names and "mcp_get_prompt" in names
    assert "mcp_list_resources" not in names


def test_no_gateway_tools_when_neither():
    rt = FakeMCPRuntime2()
    names = _names(build_tool_schemas(rt))
    for n in ("mcp_list_resources", "mcp_read_resource", "mcp_list_prompts", "mcp_get_prompt"):
        assert n not in names


def test_dispatch_read_resource():
    rt = FakeMCPRuntime2(resources=[("s", {"uri": "file:///a", "name": "", "description": "", "mimeType": ""})])
    out = dispatch_tool("mcp_read_resource", '{"server": "s", "uri": "file:///a"}',
                        allowed_roots=[], cwd=Path("."), timeout=10, mcp_runtime=rt)
    assert out == "RES:s:file:///a"
    assert rt.reads == [("s", "file:///a")]


def test_dispatch_get_prompt():
    rt = FakeMCPRuntime2(prompts=[("s", {"name": "p", "description": "", "arguments": []})])
    out = dispatch_tool("mcp_get_prompt", '{"server": "s", "name": "p", "arguments": {"n": 1}}',
                        allowed_roots=[], cwd=Path("."), timeout=10, mcp_runtime=rt)
    assert out == "PROMPT:s:p:{'n': 1}"


def test_dispatch_list_resources_enumerates():
    rt = FakeMCPRuntime2(resources=[("s", {"uri": "file:///a", "name": "Doc", "description": "x", "mimeType": "text/plain"})])
    out = dispatch_tool("mcp_list_resources", "{}", allowed_roots=[], cwd=Path("."), timeout=10, mcp_runtime=rt)
    assert "file:///a" in out and "s" in out


def test_describe_call_gateway():
    assert describe_call("mcp_read_resource", '{"server": "s", "uri": "file:///a"}') == "mcp_read_resource → read resource file:///a from s"
    assert describe_call("mcp_get_prompt", '{"server": "s", "name": "p"}') == "mcp_get_prompt → prompt p from s"


def _names(schemas):
    return {s["function"]["name"] for s in schemas}


def test_schemas_omit_spawn_agent_by_default():
    assert "spawn_agent" not in _names(build_tool_schemas())


def test_schemas_include_spawn_agent_when_can_spawn():
    assert "spawn_agent" in _names(build_tool_schemas(can_spawn=True))


def test_dispatch_spawn_agent_calls_spawn_fn(tmp_path):
    seen = {}
    def spawn_fn(task, role, instructions):
        seen["task"] = task
        seen["role"] = role
        seen["instructions"] = instructions
        return "child report"
    out = dispatch_tool(
        "spawn_agent",
        '{"task": "look at X", "role": "researcher"}',
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=1.0, spawn_fn=spawn_fn,
    )
    assert out == "child report"
    assert seen == {"task": "look at X", "role": "researcher", "instructions": None}


def test_dispatch_spawn_agent_without_spawn_fn_is_unknown_tool(tmp_path):
    out = dispatch_tool(
        "spawn_agent", '{"task": "x"}',
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=1.0,
    )
    assert "unknown tool" in out.lower()


def test_dispatch_spawn_agent_missing_task_is_clean_error(tmp_path):
    out = dispatch_tool(
        "spawn_agent", '{"role": "researcher"}',
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=1.0, spawn_fn=lambda *a: "x",
    )
    assert out.startswith("Error: missing required argument")


def test_describe_call_spawn_agent():
    d = describe_call("spawn_agent", '{"task": "review the diff", "role": "reviewer"}')
    assert "spawn_agent" in d
    assert "reviewer" in d


def test_schemas_include_spawn_agents_when_can_spawn():
    names = {s["function"]["name"] for s in build_tool_schemas(can_spawn=True)}
    assert "spawn_agents" in names
    assert "spawn_agent" in names  # both present


def test_schemas_omit_spawn_agents_by_default():
    names = {s["function"]["name"] for s in build_tool_schemas()}
    assert "spawn_agents" not in names


def test_dispatch_spawn_agents_calls_fn(tmp_path):
    seen = {}
    def fn(tasks):
        seen["tasks"] = tasks
        return "aggregate report"
    out = dispatch_tool(
        "spawn_agents", '{"tasks": [{"task": "a"}, {"task": "b", "role": "reviewer"}]}',
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=1.0, spawn_agents_fn=fn,
    )
    assert out == "aggregate report"
    assert seen["tasks"] == [{"task": "a"}, {"task": "b", "role": "reviewer"}]


def test_dispatch_spawn_agents_without_fn_is_unknown_tool(tmp_path):
    out = dispatch_tool("spawn_agents", '{"tasks": [{"task": "a"}]}',
                        allowed_roots=[tmp_path], cwd=tmp_path, timeout=1.0)
    assert "unknown tool" in out.lower()


def test_dispatch_spawn_agents_missing_tasks_is_clean_error(tmp_path):
    out = dispatch_tool("spawn_agents", '{}',
                        allowed_roots=[tmp_path], cwd=tmp_path, timeout=1.0,
                        spawn_agents_fn=lambda tasks: "x")
    assert out.startswith("Error: missing required argument")


def test_describe_call_spawn_agents():
    d = describe_call("spawn_agents", '{"tasks": [{"task": "review bugs"}, {"task": "review perf"}]}')
    assert "spawn_agents" in d
    assert "2 agents" in d
