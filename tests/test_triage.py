from heya.reproduction import parse_issue_context
from heya.triage import (
    PRIORITIES, ROUTES, gate_priority, render_triage_report, render_triage_comment,
    render_pick_list,
)


def _ctx():
    return parse_issue_context({"source": "WOO-1", "steps": ["x"], "expected": "a",
                                "actual": "b", "wp_version": "6.5"})


def test_gate_priority_close_only_on_closeable():
    assert gate_priority("close", "fixed-since-report") == "close"
    assert gate_priority("close", "cannot-reproduce") == "close"
    assert gate_priority("close", "reproduced") == "medium"   # cannot close a live bug
    assert gate_priority("close", "blocked") == "medium"
    assert gate_priority("high", "reproduced") == "high"
    assert gate_priority("bogus", "reproduced") == "medium"   # unknown -> medium


def test_render_triage_report_decision_bar():
    out = render_triage_report(
        _ctx(), verdict="reproduced", what_happens="Coupon discounts the wrong price.",
        impact="All stores using variation coupons; checkout shows wrong total; no workaround.",
        priority="high", evidence=["evidence/cart.png"], repro_link="https://playground/...",
        candidate_area="class-wc-cart.php apply_coupon", next_step="assign to dev",
        version_results=[("6.5 / 8.7", "reproduced")], diagnosis_summary="conflict in coupon calc",
        solution_summary="snippet recalculates on variation")
    assert "reproduced" in out and "high" in out
    assert "Coupon discounts the wrong price." in out
    assert "evidence/cart.png" in out and "https://playground/..." in out
    assert "assign to dev" in out
    assert "—" not in out  # no em dash
    assert "posted" not in out.lower()


def test_render_triage_comment_is_compressed_and_postless():
    out = render_triage_comment(
        _ctx(), verdict="reproduced", what_happens="Wrong total.",
        impact="affects checkout", priority="high", evidence=["e"],
        repro_link="https://x", next_step="assign")
    assert "high" in out and "https://x" in out
    assert "—" not in out and "posting" not in out.lower()


def test_render_pick_list_routes():
    items = [
        {"id": "WOO-1", "title": "coupon bug", "complexity": 3, "route": "ready-to-fix",
         "reason": "clear steps", "action": "/bug-blitz WOO-1"},
        {"id": "WOO-2", "title": "vague", "complexity": 7, "route": "needs-info",
         "reason": "no steps", "action": "ask reporter"},
        {"id": "WOO-3", "title": "x", "complexity": 2, "route": "teleport",  # invalid route
         "reason": "y", "action": "z"},
    ]
    out = render_pick_list("Linear view woo-blitz", items)
    assert "WOO-1" in out and "ready-to-fix" in out
    assert "WOO-3" in out and "skip" in out and "invalid route" in out  # invalid -> skip
    assert render_pick_list("src", []).strip() != ""  # empty -> a real "no issues" body


def test_routes_and_priorities_constants():
    assert set(PRIORITIES) == {"high", "medium", "low", "close"}
    assert "ready-to-fix" in ROUTES and "skip" in ROUTES
