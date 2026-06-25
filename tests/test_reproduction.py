from pathlib import Path

import pytest

from heya.reproduction import (
    VERDICTS, IssueContext, parse_issue_context, repro_workdir,
    gate_verdict, render_report, render_comment,
)


def _full_fields():
    return {
        "source": "linear:WOO-1",
        "steps": ["add product to cart", "apply coupon SAVE10"],
        "expected": "10% off the variation price",
        "actual": "10% off the parent price",
        "wp_version": "6.5",
        "wc_version": "8.7",
        "plugins": ["woocommerce:8.7"],
        "theme": "storefront",
        "settings": ["enable taxes"],
        "seed_data": ["1 variable product"],
    }


def test_parse_full_has_no_missing():
    ctx = parse_issue_context(_full_fields())
    assert ctx.missing == ()
    assert ctx.steps == ("add product to cart", "apply coupon SAVE10")
    assert ctx.expected.startswith("10% off the variation")


def test_parse_missing_required_fields():
    ctx = parse_issue_context({"steps": ["do x"]})
    assert "expected" in ctx.missing
    assert "actual" in ctx.missing
    assert "version (wp/wc/php)" in ctx.missing
    assert "steps" not in ctx.missing


def test_parse_version_satisfied_by_any_one():
    ctx = parse_issue_context({
        "steps": ["x"], "expected": "a", "actual": "b", "php_version": "8.2"})
    assert ctx.missing == ()


def test_gate_blocks_non_blocked_without_evidence():
    for v in ("reproduced", "fixed-since-report", "cannot-reproduce"):
        assert gate_verdict(v, []) == "blocked"


def test_gate_keeps_verdict_with_evidence():
    assert gate_verdict("reproduced", ["evidence/step3.png"]) == "reproduced"


def test_gate_blocked_stays_blocked():
    assert gate_verdict("blocked", ["x"]) == "blocked"


def test_gate_unknown_verdict_is_blocked():
    assert gate_verdict("totally-fixed", ["x"]) == "blocked"


def test_repro_workdir_creates_evidence_dir(tmp_path):
    base = repro_workdir("WOO-1", allowed_roots=[tmp_path], cwd=tmp_path)
    assert base.is_dir()
    assert (base / "evidence").is_dir()
    assert base.name == "WOO-1"
    assert base.parent.name == "repro"


def test_repro_workdir_sanitizes_traversal(tmp_path):
    # A slug trying to escape is sanitized to a safe name, still inside repro/.
    base = repro_workdir("../../etc/passwd", allowed_roots=[tmp_path], cwd=tmp_path)
    assert tmp_path in base.parents
    assert ".." not in base.name


def test_render_report_contains_verdict_and_evidence():
    ctx = parse_issue_context(_full_fields())
    out = render_report(
        ctx, "reproduced", ["evidence/cart.png"],
        what_happens="Coupon discounts the wrong price.",
        summary="Discount applied to parent, not variation.",
        version_results=[("6.5 / 8.7", "reproduced")],
        suggested_next_step="assign to dev",
    )
    assert "reproduced" in out
    assert "evidence/cart.png" in out
    assert "Coupon discounts the wrong price." in out
    assert "—" not in out  # no em dash


def test_render_comment_is_plain_and_postless():
    ctx = parse_issue_context(_full_fields())
    out = render_comment(
        ctx, "reproduced", ["evidence/cart.png"],
        what_happens="Coupon discounts the wrong price.",
        summary="Discount applied to parent, not variation.",
        version_results=[("6.5 / 8.7", "reproduced")],
        suggested_next_step="assign to dev",
    )
    assert "reproduced" in out
    assert "—" not in out
