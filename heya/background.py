"""Background sub-agents: run Agent loops on daemon threads, track status and
output, and lease write scopes so concurrent writers never collide. In-process
only; threads end when Heya exits. Modeled on heya/process.py."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class BackgroundAgent:
    id: str
    task: str
    role: str | None = None
    write_scope: Path | None = None
    allow_commands: bool = False
    status: str = "running"  # running | done | failed | cancelled
    result: str = ""
    started: float = 0.0
    finished: float = 0.0
    buffer: list[str] = field(default_factory=list)
    cursor: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    cancel: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    process_registry: object | None = None  # the child's ProcessRegistry, for cancel
    _drained: bool = False


def _within(path: Path, scope: Path) -> bool:
    """True if `path` is `scope` or inside it (both already resolved)."""
    return path == scope or scope in path.parents


class BackgroundRegistry:
    def __init__(self, *, max_concurrent: int = 4, clock: Callable[[], float] = time.monotonic) -> None:
        self._agents: dict[str, BackgroundAgent] = {}
        self._counter = 0
        self._max = max_concurrent
        self._lock = threading.Lock()
        self._clock = clock

    # ---- lifecycle ----

    def start(self, run, *, task, role=None, instructions=None,
              write_scope=None, allow_commands=False):
        scope = Path(write_scope).resolve() if write_scope else None
        with self._lock:
            running = [a for a in self._agents.values() if a.status == "running"]
            if len(running) >= self._max:
                return (f"Error: at the background agent limit ({self._max}). "
                        f"Use collect_agent on a finished one or cancel_agent first.")
            if scope is not None:
                for a in running:
                    if a.write_scope is not None and (
                            _within(scope, a.write_scope) or _within(a.write_scope, scope)):
                        return (f"Error: write scope {scope} overlaps background agent "
                                f"{a.id}'s scope {a.write_scope}. Choose a separate folder.")
            self._counter += 1
            agent_id = f"a{self._counter}"
            entry = BackgroundAgent(
                id=agent_id, task=task, role=role, write_scope=scope,
                allow_commands=allow_commands, started=self._clock())
            self._agents[agent_id] = entry

        def _sink(text: str) -> None:
            with entry.lock:
                entry.buffer.append(text)

        def _work() -> None:
            try:
                entry.result = run(entry, _sink)
                entry.status = "cancelled" if entry.cancel.is_set() else "done"
            except Exception as exc:  # never propagate from a thread
                entry.result = f"Error: background agent failed: {exc}"
                entry.status = "failed"
            finally:
                entry.finished = self._clock()

        entry.thread = threading.Thread(target=_work, daemon=True)
        entry.thread.start()
        return entry

    # ---- polling / collection ----

    def _require(self, id: str) -> BackgroundAgent | None:
        return self._agents.get(id)

    def poll(self, id: str) -> str:
        entry = self._require(id)
        if entry is None:
            return f"Error: no background agent {id!r}."
        with entry.lock:
            new = entry.buffer[entry.cursor:]
            entry.cursor = len(entry.buffer)
        body = "".join(new).strip() or "(no new output)"
        return f"[{id} {entry.status}]\n{body}"

    def summaries(self) -> list[dict]:
        out = []
        for a in self._agents.values():
            out.append({"id": a.id, "task": a.task[:80], "status": a.status,
                        "scope": str(a.write_scope) if a.write_scope else None})
        return out

    def collect(self, id: str) -> str:
        entry = self._require(id)
        if entry is None:
            return f"Error: no background agent {id!r}."
        if entry.status == "running":
            return f"[{id}] still running. Use check_agent('{id}') for progress."
        return entry.result or f"[{id}] {entry.status} with no output."

    def cancel(self, id: str) -> str:
        entry = self._require(id)
        if entry is None:
            return f"Error: no background agent {id!r}."
        entry.cancel.set()
        reg = entry.process_registry
        if reg is not None and hasattr(reg, "close"):
            try:
                reg.close()  # terminate the child's background shell processes
            except Exception:
                pass
        return f"Cancelling background agent {id}. It stops at its next checkpoint."

    def drain_finished(self) -> list[BackgroundAgent]:
        done = []
        for a in self._agents.values():
            if a.status != "running" and not a._drained:
                a._drained = True
                done.append(a)
        return done

    # ---- leases ----

    def check_write(self, path, owner_id: str) -> str | None:
        p = Path(path).resolve()
        with self._lock:
            for a in self._agents.values():
                if a.status != "running" or a.write_scope is None or a.id == owner_id:
                    continue
                if _within(p, a.write_scope):
                    return (f"Error: {path} is being written by background agent {a.id}. "
                            f"Wait for it or cancel_agent('{a.id}').")
            owner = self._agents.get(owner_id)
            if owner is not None and owner.write_scope is not None and not _within(p, owner.write_scope):
                return (f"Error: background agent {owner_id} may only write inside "
                        f"{owner.write_scope}.")
        return None

    # ---- persistence / shutdown ----

    def snapshot(self) -> list[dict]:
        return [{"id": a.id, "task": a.task[:120], "status": a.status,
                 "result": (a.result or "")[:2000]}
                for a in self._agents.values() if a.status != "running"]

    def running_ids(self) -> list[str]:
        return [a.id for a in self._agents.values() if a.status == "running"]
