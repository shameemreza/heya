import shutil as _shutil
import sys

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


from heya.tools_wp import PlaygroundSession


class _FakeReg:
    def __init__(self, output=""):
        self._output = output
        self.killed = []

    def start(self, cmd, *, cwd):
        from heya.process import ManagedProcess
        self.cmd = cmd
        return ManagedProcess(id="p1", pid=99)

    def peek(self, id):
        return self._output

    def kill(self, id):
        self.killed.append(id)
        return f"Killed background process {id}."


def test_playground_start_returns_url(tmp_path, monkeypatch):
    monkeypatch.setattr(wp_mod.shutil, "which", lambda _: "/usr/bin/npx")
    reg = _FakeReg(output="Server running at http://127.0.0.1:9400")
    sess = PlaygroundSession(reg, cwd=tmp_path)
    out = sess.start()
    assert "http://127.0.0.1:9400" in out and "@wp-playground/cli" in reg.cmd


def test_playground_missing_npx_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(wp_mod.shutil, "which", lambda _: None)
    sess = PlaygroundSession(_FakeReg(), cwd=tmp_path)
    out = sess.start()
    assert "Playground is not available" in out


def test_playground_stop_kills(tmp_path, monkeypatch):
    monkeypatch.setattr(wp_mod.shutil, "which", lambda _: "/usr/bin/npx")
    reg = _FakeReg(output="http://127.0.0.1:9400")
    sess = PlaygroundSession(reg, cwd=tmp_path)
    sess.start()
    sess.stop()
    assert reg.killed == ["p1"]


@pytest.mark.integration
def test_wp_cli_info_live(tmp_path):
    if _shutil.which("wp") is None:
        pytest.skip("wp not installed")
    # `wp --info` does not need an install; just proves the wrapper executes wp.
    out = wp_mod.run_wp_cli("--info", str(tmp_path), allowed_roots=[tmp_path], cwd=tmp_path, timeout=30)
    assert "PHP" in out or "WP-CLI" in out


@pytest.mark.integration
def test_process_registry_real_background(tmp_path):
    from heya.process import ProcessRegistry
    import time
    reg = ProcessRegistry()
    try:
        mp = reg.start(f'{sys.executable} -u -c "import time; print(\'up\'); time.sleep(30)"', cwd=tmp_path)
        time.sleep(1.0)
        assert "up" in reg.peek(mp.id)
        reg.kill(mp.id)
    finally:
        reg.close()
