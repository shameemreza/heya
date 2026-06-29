import time

from heya.background import BackgroundRegistry


def _wait(predicate, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_two_concurrent_agents_finish_and_drain():
    reg = BackgroundRegistry(max_concurrent=2)

    def make_run(tag):
        def run(entry, on_text):
            on_text(f"{tag} working")
            return f"{tag} result"
        return run

    a = reg.start(make_run("A"), task="task A")
    b = reg.start(make_run("B"), task="task B")
    assert _wait(lambda: a.status == "done" and b.status == "done")
    drained = {x.id for x in reg.drain_finished()}
    assert drained == {"a1", "a2"}
    snap = reg.snapshot()
    assert {row["id"] for row in snap} == {"a1", "a2"}
    assert all(row["status"] == "done" for row in snap)
