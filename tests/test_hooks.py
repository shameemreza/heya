import json
from pathlib import Path

from heya.hooks import (
    HookSpec, HookOutcome, parse_hooks_config, collect_hooks, tool_matches,
    hook_payload, run_command_hook, fire_hooks,
)

_BLOCK_CFG = {"hooks": {"PreToolUse": [
    {"matcher": "Bash", "hooks": [{"type": "command", "command": "validate.sh", "timeout": 5}]}]}}


def test_parse_hooks_config_command_only():
    specs = parse_hooks_config({"hooks": {"PreToolUse": [
        {"matcher": "Write", "hooks": [
            {"type": "command", "command": "a.sh"},
            {"type": "http", "url": "http://x"},  # skipped (not command)
        ]}]}})
    assert len(specs) == 1
    assert specs[0].event == "PreToolUse" and specs[0].command == "a.sh"


def test_parse_hooks_config_skips_malformed():
    assert parse_hooks_config({"hooks": {"X": "notalist"}}) == []
    assert parse_hooks_config("nope") == []


def test_tool_matches_alias_and_forms():
    assert tool_matches("*", "run_command") is True
    assert tool_matches("", "run_command") is True
    assert tool_matches("Bash", "run_command") is True          # alias
    assert tool_matches("run_command", "run_command") is True   # native
    assert tool_matches("Write|Edit", "write_file") is True     # OR + alias
    assert tool_matches("read_file", "run_command") is False


def test_hook_payload_fields():
    p = hook_payload("PreToolUse", session_id="s1", cwd="/c", tool_name="run_command",
                     tool_input='{"cmd":"ls"}')
    assert p["hook_event_name"] == "PreToolUse"
    assert p["session_id"] == "s1" and p["cwd"] == "/c"
    assert p["tool_name"] == "run_command"


def test_run_command_hook_block_on_exit_2():
    spec = HookSpec("PreToolUse", "Bash", "x.sh", (), 5.0, "cfg")

    def runner(s, *, stdin):
        return (2, "", "denied by policy")

    out = run_command_hook(spec, {"x": 1}, runner=runner)
    assert out.block is True
    assert "denied by policy" in out.message


def test_run_command_hook_no_block_on_exit_0():
    spec = HookSpec("PreToolUse", "Bash", "x.sh", (), 5.0, "cfg")
    out = run_command_hook(spec, {}, runner=lambda s, *, stdin: (0, "", ""))
    assert out.block is False


def test_run_command_hook_continue_false_blocks():
    spec = HookSpec("PreToolUse", "Bash", "x.sh", (), 5.0, "cfg")
    out = run_command_hook(spec, {}, runner=lambda s, *, stdin: (0, '{"continue": false}', ""))
    assert out.block is True


def test_run_command_hook_runner_raises_is_nonblocking():
    spec = HookSpec("PostToolUse", "*", "x.sh", (), 5.0, "cfg")

    def runner(s, *, stdin):
        raise RuntimeError("boom")

    out = run_command_hook(spec, {}, runner=runner)
    assert out.block is False  # never raises out


def test_fire_hooks_disabled_is_noop():
    spec = HookSpec("PreToolUse", "*", "x.sh", (), 5.0, "cfg")
    calls = []
    out = fire_hooks("PreToolUse", {"PreToolUse": [spec]}, {}, enabled=False,
                     runner=lambda s, *, stdin: calls.append(1) or (2, "", ""),
                     tool_name="run_command")
    assert out.block is False and calls == []


def test_fire_hooks_blocks_and_filters_by_tool():
    block = HookSpec("PreToolUse", "Bash", "x.sh", (), 5.0, "cfg")
    notes = []
    out = fire_hooks("PreToolUse", {"PreToolUse": [block]}, {}, enabled=True,
                     runner=lambda s, *, stdin: (2, "", "no"), tool_name="run_command",
                     on_note=notes.append)
    assert out.block is True and notes  # fired + noted
    # a hook whose matcher does not match the tool does not fire
    out2 = fire_hooks("PreToolUse", {"PreToolUse": [block]}, {}, enabled=True,
                      runner=lambda s, *, stdin: (2, "", "no"), tool_name="read_file")
    assert out2.block is False


def test_collect_hooks_from_files(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text(json.dumps(_BLOCK_CFG))
    by_event = collect_hooks([f, tmp_path / "missing.json"])
    assert "PreToolUse" in by_event and by_event["PreToolUse"][0].command == "validate.sh"
