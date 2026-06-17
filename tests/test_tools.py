import json

import pytest

from heya.tools import TOOL_SCHEMAS, dispatch_tool, describe_call


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
