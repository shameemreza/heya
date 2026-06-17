import json

import pytest

from heya.tools import TOOL_SCHEMAS, dispatch_tool, describe_call


def test_schemas_cover_the_three_tools():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert names == {"read_file", "write_file", "run_command"}
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
