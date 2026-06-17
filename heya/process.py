"""A registry of long-lived background subprocesses, addressable by a short id.

Unlike run_command (run-to-completion with a timeout), these are servers,
watchers, and Playground instances that must be started, polled for new output,
and killed by handle. Each runs in its own process group so kill takes the whole
tree, closing the backgrounded-grandchild gap in the cwd-sandbox. Output is
drained on a daemon thread into a buffer; poll() returns only what is new since
the previous poll. Once a process is reaped, status stays terminal — it never
re-emits "still running".
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .tools_files import ToolError


@dataclass
class ManagedProcess:
    id: str
    pid: int


@dataclass
class _Entry:
    proc: subprocess.Popen
    buffer: list[str] = field(default_factory=list)
    cursor: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    reader: threading.Thread | None = None


class ProcessRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._counter = 0

    def start(self, cmd: str, *, cwd: Path) -> ManagedProcess:
        self._counter += 1
        pid_id = f"p{self._counter}"
        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,  # own process group for group-kill
        )
        entry = _Entry(proc=proc)

        def _drain() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                with entry.lock:
                    entry.buffer.append(line.rstrip("\n"))

        entry.reader = threading.Thread(target=_drain, daemon=True)
        entry.reader.start()
        self._entries[pid_id] = entry
        return ManagedProcess(id=pid_id, pid=proc.pid)

    def _require(self, id: str) -> _Entry:
        entry = self._entries.get(id)
        if entry is None:
            raise ToolError(f"No such background process {id!r}.")
        return entry

    def _status(self, entry: _Entry) -> str:
        code = entry.proc.poll()
        return "running" if code is None else f"exited (code {code})"

    def peek(self, id: str) -> str:
        entry = self._require(id)
        with entry.lock:
            return "\n".join(entry.buffer)

    def poll(self, id: str) -> str:
        entry = self._require(id)
        with entry.lock:
            new = entry.buffer[entry.cursor:]
            entry.cursor = len(entry.buffer)
        body = "\n".join(new) if new else "(no new output)"
        return f"[{id} {self._status(entry)}]\n{body}"

    def kill(self, id: str) -> str:
        entry = self._require(id)
        if entry.proc.poll() is None:
            try:
                os.killpg(os.getpgid(entry.proc.pid), signal.SIGTERM)
                try:
                    entry.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(entry.proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        return f"Killed background process {id}."

    def close(self) -> None:
        for id in list(self._entries):
            try:
                self.kill(id)
            except Exception:
                pass
