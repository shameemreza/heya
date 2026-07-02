import shutil
import pytest
from heya import tools_wp


def test_wp_cli_does_not_chain_shell(tmp_path, monkeypatch):
    monkeypatch.setattr(tools_wp.shutil, "which", lambda n: "/usr/bin/wp")
    captured = {}

    def fake_run_command(cmd, *, cwd, allowed_roots, timeout):
        captured["cmd"] = cmd
        from heya.tools_files import CommandResult
        return CommandResult(stdout="", stderr="", exit_code=0)

    monkeypatch.setattr(tools_wp, "run_command", fake_run_command)
    tools_wp.run_wp_cli("plugin list ; rm -rf ~", str(tmp_path),
                        allowed_roots=[tmp_path], cwd=tmp_path, timeout=5.0)
    assert isinstance(captured["cmd"], list)
    assert ";" in captured["cmd"]  # the ';' is a literal argv token, not a shell operator
    assert captured["cmd"][0] == "wp"
