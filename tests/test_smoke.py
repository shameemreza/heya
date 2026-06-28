"""End-to-end smoke checks: the CLI starts, and the deliverable renders offline.

These prove the quickstart in the README is real, not aspirational. They do not
need a live model."""

import subprocess
import sys


def test_heya_help_runs():
    proc = subprocess.run(
        [sys.executable, "-m", "heya.main", "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0
    assert "heya" in (proc.stdout + proc.stderr).lower()


def test_triage_render_path_offline():
    from heya.reproduction import parse_issue_context
    from heya.triage import render_triage_report, gate_priority

    ctx = parse_issue_context({"source": "WOO-1", "wp_version": "6.5"})
    out = render_triage_report(
        ctx, verdict="reproduced", what_happens="w", impact="i",
        priority=gate_priority("high", "reproduced"), evidence=["e"],
        repro_link="http://x", candidate_area="c", next_step="n",
        version_results=[("6.5", "reproduced")],
    )
    assert "reproduced" in out and "WOO-1" in out
