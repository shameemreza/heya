import threading
import time

from heya.agent import Agent
from heya.background import BackgroundAgent, BackgroundRegistry


def _runner(text, *, block=None):
    """A fake `run` callable: emit text, optionally block on an event, return result."""
    def run(entry, on_text):
        on_text(text)
        if block is not None:
            block.wait(timeout=2)
        return f"done: {text}"
    return run


def _wait_until(predicate, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_start_returns_entry_with_id_and_runs():
    reg = BackgroundRegistry()
    entry = reg.start(_runner("hello"), task="say hi")
    assert isinstance(entry, BackgroundAgent)
    assert entry.id == "a1"
    assert _wait_until(lambda: reg.collect(entry.id).startswith("done: hello"))


def test_poll_returns_new_output_then_nothing_new():
    reg = BackgroundRegistry()
    entry = reg.start(_runner("chunk-one"), task="t")
    assert _wait_until(lambda: "chunk-one" in reg.poll(entry.id))
    later = reg.poll(entry.id)
    assert "chunk-one" not in later  # cursor advanced


def test_capacity_refuses_beyond_max():
    block = threading.Event()
    reg = BackgroundRegistry(max_concurrent=1)
    first = reg.start(_runner("a", block=block), task="t")
    assert isinstance(first, BackgroundAgent)
    refused = reg.start(_runner("b"), task="t2")
    assert isinstance(refused, str) and "Error" in refused
    block.set()


def test_collect_reports_running_then_result():
    block = threading.Event()
    reg = BackgroundRegistry()
    entry = reg.start(_runner("x", block=block), task="t")
    assert "still running" in reg.collect(entry.id).lower()
    block.set()
    assert _wait_until(lambda: "done: x" in reg.collect(entry.id))


def test_cancel_sets_event_and_marks_cancelled():
    started = threading.Event()
    seen_cancel = threading.Event()

    def run(entry, on_text):
        started.set()
        for _ in range(200):
            if entry.cancel.is_set():
                seen_cancel.set()
                return "stopped"
            time.sleep(0.01)
        return "ran to end"

    reg = BackgroundRegistry()
    entry = reg.start(run, task="loop")
    assert started.wait(1)
    out = reg.cancel(entry.id)
    assert "a1" in out
    assert seen_cancel.wait(1)
    assert _wait_until(lambda: reg.summaries()[0]["status"] == "cancelled")


def test_drain_finished_returns_each_agent_once():
    reg = BackgroundRegistry()
    entry = reg.start(_runner("y"), task="t")
    assert _wait_until(lambda: entry.status == "done")
    drained = reg.drain_finished()
    assert [a.id for a in drained] == ["a1"]
    assert reg.drain_finished() == []  # only once


def test_failure_is_captured_not_raised():
    def run(entry, on_text):
        raise RuntimeError("boom")

    reg = BackgroundRegistry()
    entry = reg.start(run, task="t")
    assert _wait_until(lambda: entry.status == "failed")
    assert "boom" in reg.collect(entry.id)


def test_lease_blocks_foreground_inside_scope(tmp_path):
    block = threading.Event()
    reg = BackgroundRegistry()
    scope = tmp_path / "plugin"
    scope.mkdir()
    entry = reg.start(_runner("x", block=block), task="build", write_scope=scope)
    assert isinstance(entry, BackgroundAgent)
    err = reg.check_write(scope / "main.php", "main")
    assert err and entry.id in err
    block.set()


def test_lease_allows_foreground_outside_scope(tmp_path):
    block = threading.Event()
    reg = BackgroundRegistry()
    scope = tmp_path / "plugin"
    scope.mkdir()
    reg.start(_runner("x", block=block), task="build", write_scope=scope)
    assert reg.check_write(tmp_path / "other" / "file.txt", "main") is None
    block.set()


def test_lease_refuses_overlapping_scope(tmp_path):
    block = threading.Event()
    reg = BackgroundRegistry()
    scope = tmp_path / "plugin"
    scope.mkdir()
    reg.start(_runner("a", block=block), task="t", write_scope=scope)
    refused = reg.start(_runner("b"), task="t2", write_scope=scope / "sub")
    assert isinstance(refused, str) and "overlap" in refused.lower()
    block.set()


def test_two_nonoverlapping_writers_both_allowed(tmp_path):
    block = threading.Event()
    reg = BackgroundRegistry(max_concurrent=2)
    a = reg.start(_runner("a", block=block), task="t", write_scope=tmp_path / "p1")
    b = reg.start(_runner("b", block=block), task="t2", write_scope=tmp_path / "p2")
    assert isinstance(a, BackgroundAgent) and isinstance(b, BackgroundAgent)
    block.set()


def test_owner_may_write_inside_its_scope_only(tmp_path):
    block = threading.Event()
    reg = BackgroundRegistry()
    scope = tmp_path / "plugin"
    scope.mkdir()
    entry = reg.start(_runner("x", block=block), task="t", write_scope=scope)
    assert reg.check_write(scope / "inc" / "f.php", entry.id) is None
    outside = reg.check_write(tmp_path / "elsewhere.txt", entry.id)
    assert outside and "only write inside" in outside
    block.set()


def test_command_grant_text_warns_full_shell(tmp_path):
    """When allow_commands=True, the approval detail must state the shell is unconfined."""
    captured = []

    class RecordingApprover:
        def check(self, name, detail, label=""):
            return True

        def confirm(self, detail, label=""):
            captured.append(detail)
            return False  # decline so no background thread starts

    reg = BackgroundRegistry()
    agent = Agent(
        object(),  # client is never called: approval declines before any thread starts
        allowed_roots=[tmp_path],
        cwd=tmp_path,
        approval=RecordingApprover(),
        self_review=False,
        background_registry=reg,
    )

    agent._spawn_background_agent(
        task="build plugin",
        role=None,
        instructions=None,
        write_scope=None,
        allow_commands=True,
    )

    assert captured, "approval.confirm was not called"
    text = captured[0]
    assert "full shell" in text or "not confined" in text, (
        f"grant text does not warn about unconfined shell: {text!r}"
    )
