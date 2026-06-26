from heya.reproduction import parse_issue_context
from heya.remediation import (
    FIX_KINDS, check_fix_safety, gate_fix_verdict, repair_should_stop,
    fix_grounded, render_solution,
)


def test_check_fix_safety_setting_json():
    ok, msg = check_fix_safety("setting", '{"woocommerce_enable_guest_checkout": "yes"}')
    assert ok
    bad, msg2 = check_fix_safety("setting", "{not json")
    assert not bad


def test_check_fix_safety_php_balanced():
    ok, _ = check_fix_safety("snippet", "<?php add_filter('x', function($v){ return $v; });")
    assert ok
    bad, _ = check_fix_safety("snippet", "<?php function f(){ return 1;")
    assert not bad  # unbalanced braces


def test_check_fix_safety_php_needs_open_tag():
    bad, msg = check_fix_safety("snippet", "add_filter('x', '__return_true');")
    assert not bad
    assert "php" in msg.lower()


def test_check_fix_safety_unknown_kind():
    ok, _ = check_fix_safety("teleport", "x")
    assert not ok


def test_gate_fix_verdict_requires_both_oracles_and_evidence():
    assert gate_fix_verdict(repro_passes=True, regression_passes=True, evidence=["e"]) == "verified"
    assert gate_fix_verdict(repro_passes=True, regression_passes=False, evidence=["e"]) == "not-verified"
    assert gate_fix_verdict(repro_passes=False, regression_passes=True, evidence=["e"]) == "not-verified"
    assert gate_fix_verdict(repro_passes=True, regression_passes=True, evidence=[]) == "not-verified"


def test_repair_should_stop_cap():
    attempts = [{"patch": "a", "signature": "s1"}, {"patch": "b", "signature": "s2"},
                {"patch": "c", "signature": "s3"}]
    stop, reason = repair_should_stop(attempts, "d", cap=3)
    assert stop and "cap" in reason.lower()


def test_repair_should_stop_identical_candidate():
    attempts = [{"patch": "<?php  return 1;", "signature": "s1"}]
    stop, reason = repair_should_stop(attempts, "<?php return 1;", cap=3)  # whitespace-equal
    assert stop and "identical" in reason.lower()


def test_repair_should_stop_repeated_signature():
    attempts = [{"patch": "a", "signature": "sigX"}, {"patch": "b", "signature": "sigX"}]
    stop, reason = repair_should_stop(attempts, "c", cap=3)
    assert stop and "signature" in reason.lower()


def test_repair_should_stop_verified_short_circuits():
    attempts = [{"patch": "a", "signature": "s1", "verified": True}]
    stop, reason = repair_should_stop(attempts, "b", cap=3)
    assert stop and "verified" in reason.lower()


def test_repair_should_continue():
    attempts = [{"patch": "a", "signature": "s1"}]
    stop, _ = repair_should_stop(attempts, "b", cap=3)
    assert not stop


def test_fix_grounded_exact():
    assert fix_grounded("VERDICT: grounded\ngrounding: ok") is True
    assert fix_grounded("VERDICT: ungrounded") is False
    assert fix_grounded("nope") is False


def test_render_solution_labels_workaround():
    ctx = parse_issue_context({"source": "WOO-1", "steps": ["x"], "expected": "a",
                               "actual": "b", "wp_version": "6.5"})
    out = render_solution(ctx, kind="snippet", content="<?php return 1;",
                          verdict="verified", evidence=["repro now passes"],
                          how_to_apply="add via a snippet plugin", caveats="none")
    assert "verified" in out
    assert "unsupported workaround" in out.lower()
    assert "repro now passes" in out
    assert "—" not in out


def test_render_solution_patch_not_workaround():
    ctx = parse_issue_context({"source": "WOO-1", "steps": ["x"], "expected": "a",
                               "actual": "b", "wp_version": "6.5"})
    out = render_solution(ctx, kind="patch", content="diff", verdict="not-verified",
                          evidence=[], how_to_apply="apply the patch", caveats="")
    assert "unsupported workaround" not in out.lower()


from heya.remediation import VERIFY_REMEDIATION_PROMPT, verify_remediation


def test_verify_remediation_grounded():
    def fake_run_children(specs):
        return [(s["label"], "VERDICT: grounded\ngrounding: add_filter exists at x.php:10")
                for s in specs]
    out = verify_remediation("<?php add_filter(...)", "context", run_children=fake_run_children)
    assert out.lower().startswith("grounded")


def test_verify_remediation_ungrounded_is_unsafe():
    def fake_run_children(specs):
        return [(s["label"], "VERDICT: ungrounded\ngrounding: hook does not exist")
                for s in specs]
    out = verify_remediation("<?php do_action('made_up')", "context", run_children=fake_run_children)
    assert out.lower().startswith("unsafe")


def test_verify_remediation_error_fails_closed():
    def fake_run_children(specs):
        return [(s["label"], "Error: sub-agent failed") for s in specs]
    out = verify_remediation("fix", "context", run_children=fake_run_children)
    assert out.lower().startswith("unsafe")


def test_verify_prompt_contains_refute():
    p = VERIFY_REMEDIATION_PROMPT("fix", "context")
    assert "REFUTE" in p
