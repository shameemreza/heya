import pytest

import heya.tools_wp as wp_mod
from heya.tools_wp import read_log, resolve_wp_root
from heya.tools_files import ToolError


def _make_site(tmp_path, log_lines):
    (tmp_path / "wp-content").mkdir()
    (tmp_path / "wp-content" / "debug.log").write_text("\n".join(log_lines) + "\n")
    return tmp_path


def test_read_log_tails_last_n(tmp_path):
    _make_site(tmp_path, [f"line{i}" for i in range(500)])
    out = read_log(str(tmp_path), allowed_roots=[tmp_path], cwd=tmp_path, lines=10)
    assert "line499" in out and "line0" not in out
    assert "showing last 10 of 500" in out


def test_read_log_grep_filters(tmp_path):
    _make_site(tmp_path, ["PHP Notice: x", "PHP Fatal error: boom", "PHP Notice: y"])
    out = read_log(str(tmp_path), allowed_roots=[tmp_path], cwd=tmp_path, grep="Fatal error")
    assert "boom" in out and "Notice" not in out


def test_read_log_missing_log_message(tmp_path):
    (tmp_path / "wp-content").mkdir()
    out = read_log(str(tmp_path), allowed_roots=[tmp_path], cwd=tmp_path)
    assert "No debug.log" in out and "WP_DEBUG_LOG" in out


def test_read_log_outside_allowlist_raises(tmp_path):
    with pytest.raises(ToolError):
        read_log("/etc", allowed_roots=[tmp_path], cwd=tmp_path)


def test_resolve_wp_root_falls_back_to_default_then_cwd(tmp_path):
    assert resolve_wp_root(None, allowed_roots=[tmp_path], cwd=tmp_path) == tmp_path.resolve()
    sub = tmp_path / "site"; sub.mkdir()
    assert resolve_wp_root(None, allowed_roots=[tmp_path], cwd=tmp_path, default_root=sub) == sub.resolve()


def test_run_wp_cli_injects_path(tmp_path, monkeypatch):
    seen = {}

    def fake_run_command(cmd, *, cwd, allowed_roots, timeout):
        seen["cmd"] = cmd
        from heya.tools_files import CommandResult
        return CommandResult(stdout="ok", stderr="", exit_code=0)

    monkeypatch.setattr(wp_mod, "run_command", fake_run_command)
    monkeypatch.setattr(wp_mod.shutil, "which", lambda _: "/usr/bin/wp")
    out = wp_mod.run_wp_cli("plugin list", str(tmp_path), allowed_roots=[tmp_path], cwd=tmp_path, timeout=10)
    assert "--path=" in seen["cmd"] and "plugin list" in seen["cmd"]
    assert "ok" in out


def test_run_wp_cli_respects_user_path(tmp_path, monkeypatch):
    seen = {}

    def fake_run_command(cmd, *, cwd, allowed_roots, timeout):
        seen["cmd"] = cmd
        from heya.tools_files import CommandResult
        return CommandResult(stdout="", stderr="", exit_code=0)

    monkeypatch.setattr(wp_mod, "run_command", fake_run_command)
    monkeypatch.setattr(wp_mod.shutil, "which", lambda _: "/usr/bin/wp")
    wp_mod.run_wp_cli("plugin list --path=/custom", str(tmp_path), allowed_roots=[tmp_path], cwd=tmp_path, timeout=10)
    assert seen["cmd"].count("--path=") == 1  # did not double-inject


def test_run_wp_cli_missing_binary_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(wp_mod.shutil, "which", lambda _: None)
    out = wp_mod.run_wp_cli("plugin list", str(tmp_path), allowed_roots=[tmp_path], cwd=tmp_path, timeout=10)
    assert "WP-CLI is not available" in out
