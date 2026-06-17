import sys
import time

import pytest

from heya.process import ProcessRegistry
from heya.tools_files import ToolError

PY = sys.executable


def _wait_until(fn, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        val = fn()
        if val:
            return val
        time.sleep(0.05)
    return fn()


def test_start_returns_handle_and_captures_output(tmp_path):
    reg = ProcessRegistry()
    try:
        mp = reg.start(f'{PY} -c "print(\'hello-bg\')"', cwd=tmp_path)
        assert mp.id and mp.pid
        _wait_until(lambda: "hello-bg" in reg.peek(mp.id))
        out = reg.peek(mp.id)
        assert "hello-bg" in out
    finally:
        reg.close()


def test_poll_returns_only_new_output(tmp_path):
    reg = ProcessRegistry()
    try:
        mp = reg.start(f'{PY} -c "print(\'one\')"', cwd=tmp_path)
        _wait_until(lambda: "one" in reg.peek(mp.id))
        first = reg.poll(mp.id)
        assert "one" in first
        second = reg.poll(mp.id)
        assert "one" not in second  # already consumed; no re-emit
    finally:
        reg.close()


def test_poll_reports_exit(tmp_path):
    reg = ProcessRegistry()
    try:
        mp = reg.start(f'{PY} -c "print(123)"', cwd=tmp_path)
        _wait_until(lambda: "exited" in reg.poll(mp.id))
        status = reg.poll(mp.id)
        assert "exited" in status
    finally:
        reg.close()


def test_kill_stops_a_long_process(tmp_path):
    reg = ProcessRegistry()
    try:
        mp = reg.start(f'{PY} -c "import time; time.sleep(30)"', cwd=tmp_path)
        msg = reg.kill(mp.id)
        assert mp.id in msg
        # after kill, poll no longer reports running
        _wait_until(lambda: "running" not in reg.poll(mp.id))
        status = reg.poll(mp.id)
        assert "running" not in status
    finally:
        reg.close()


def test_unknown_id_raises_toolerror(tmp_path):
    reg = ProcessRegistry()
    with pytest.raises(ToolError):
        reg.poll("nope")
