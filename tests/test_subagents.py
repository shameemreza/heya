import pytest
import threading
import time
from heya.subagents import (
    Role, ROLES, resolve_role, build_child_system_prompt, SUBAGENT_FRAMING,
    LabeledStream, PARALLEL_SAFE_TOOLS, parallel_label, format_parallel_report,
    MAX_REPORT_CHARS, LockedSink,
)


def test_resolve_known_role_returns_role():
    role = resolve_role("researcher")
    assert isinstance(role, Role)
    assert role.name == "researcher"


def test_resolve_unknown_role_returns_none():
    assert resolve_role("nope") is None


def test_resolve_none_returns_none():
    assert resolve_role(None) is None


def test_roles_are_read_only_subsets():
    # The two starter roles must not be able to mutate.
    for key in ("researcher", "reviewer"):
        tools = ROLES[key].tools
        assert tools is not None
        assert "write_file" not in tools
        assert "run_command" not in tools
        assert "run_wp_cli" not in tools


def test_build_prompt_base_only():
    out = build_child_system_prompt("BASE", None, None)
    assert "BASE" in out
    assert SUBAGENT_FRAMING in out


def test_build_prompt_with_role_includes_addendum():
    out = build_child_system_prompt("BASE", ROLES["reviewer"], None)
    assert "BASE" in out
    assert SUBAGENT_FRAMING in out
    assert ROLES["reviewer"].system_addendum in out


def test_build_prompt_with_instructions_includes_them():
    out = build_child_system_prompt("BASE", None, "FOCUS HERE")
    assert "FOCUS HERE" in out


def test_build_prompt_with_role_and_instructions_includes_both():
    out = build_child_system_prompt("BASE", ROLES["researcher"], "EXTRA")
    assert ROLES["researcher"].system_addendum in out
    assert "EXTRA" in out


def _capture():
    out = []
    return out, out.append


def test_labeled_stream_single_line():
    out, sink = _capture()
    s = LabeledStream(sink, "researcher")
    s.write("hello\n")
    assert out == ["[researcher] hello\n"]


def test_labeled_stream_multiple_lines_one_chunk():
    out, sink = _capture()
    s = LabeledStream(sink, "r")
    s.write("a\nb\n")
    assert out == ["[r] a\n", "[r] b\n"]


def test_labeled_stream_line_split_across_chunks_gets_one_prefix():
    out, sink = _capture()
    s = LabeledStream(sink, "r")
    s.write("hel")
    s.write("lo\n")
    assert out == ["[r] hello\n"]


def test_labeled_stream_close_flushes_trailing_partial():
    out, sink = _capture()
    s = LabeledStream(sink, "r")
    s.write("no newline yet")
    assert out == []
    s.close()
    assert out == ["[r] no newline yet"]


def test_labeled_stream_empty_write_is_noop():
    out, sink = _capture()
    s = LabeledStream(sink, "r")
    s.write("")
    s.close()
    assert out == []


def test_parallel_safe_tools_are_read_only():
    for forbidden in ("write_file", "run_command", "run_wp_cli", "wp_playground",
                      "browser_navigate", "browser_click", "kill_command"):
        assert forbidden not in PARALLEL_SAFE_TOOLS
    for allowed in ("read_file", "web_search", "read_log", "mcp_read_resource"):
        assert allowed in PARALLEL_SAFE_TOOLS


def test_parallel_label():
    assert parallel_label("researcher", 1) == "researcher#1"
    assert parallel_label(None, 2) == "agent#2"


def test_format_parallel_report_ok():
    out = format_parallel_report("researcher#1", "look at X", "found Y")
    assert out.startswith("## [researcher#1] look at X")
    assert "found Y" in out


def test_format_parallel_report_status_prefix():
    failed = format_parallel_report("agent#1", "t", "boom", status="failed")
    assert "(failed)" in failed
    timed = format_parallel_report("agent#1", "t", "", status="timed-out")
    assert "(timed out)" in timed


def test_format_parallel_report_truncates_with_marker():
    big = "x" * (MAX_REPORT_CHARS + 100)
    out = format_parallel_report("agent#1", "t", big)
    assert "[report truncated]" in out
    assert len(out) < len(big) + 200  # bounded, not the full body


def test_format_parallel_report_no_marker_when_short():
    out = format_parallel_report("agent#1", "t", "short body")
    assert "[report truncated]" not in out


def test_locked_sink_serializes_concurrent_writes():
    # A deliberately non-atomic sink: appends char-by-char with a yield between,
    # so without the lock concurrent writers interleave. With the lock, each
    # write's characters stay contiguous.
    chars = []

    def slow_sink(text):
        for ch in text:
            chars.append(ch)
            time.sleep(0.0005)

    sink = LockedSink(slow_sink)
    msgs = [f"<{i:02d}>" for i in range(12)]
    threads = [threading.Thread(target=sink.write, args=(m,)) for m in msgs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    out = "".join(chars)
    assert len(out) == sum(len(m) for m in msgs)
    for m in msgs:
        assert m in out  # each message contiguous, not interleaved


from heya.subagents import BACKGROUND_TOOLS


def test_background_role_exists_and_can_write():
    assert "background" in ROLES
    assert "write_file" in BACKGROUND_TOOLS
    assert "run_command" in BACKGROUND_TOOLS
    assert PARALLEL_SAFE_TOOLS <= BACKGROUND_TOOLS  # reads still available
