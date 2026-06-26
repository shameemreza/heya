from heya.diagnosis import (
    ISSUE_CLASSES, classify_log, extract_trace_frames, Hypothesis,
    parse_hypotheses, diagnosis_confirmed, Diagnosis, render_diagnosis,
    synthesize_diagnosis, DIAGNOSIS_LENSES, HYPOTHESIS_PROMPT, VERIFY_HYPOTHESIS_PROMPT, run_diagnosis,
)


def test_classify_log_matches_patterns():
    hits = classify_log("PHP Fatal error: Allowed memory size of 134217728 bytes exhausted")
    assert ("Allowed memory size", "environment") in hits


def test_classify_log_conflict_and_typeerror():
    text = "Cannot redeclare foo()\nUncaught TypeError: bar"
    classes = {c for _, c in classify_log(text)}
    assert "conflict" in classes
    assert "bug" in classes


def test_classify_log_dedupes_and_empty():
    assert classify_log("") == []
    one = classify_log("Allowed memory size ... Allowed memory size")
    assert len([h for h in one if h[0] == "Allowed memory size"]) == 1


def test_extract_trace_frames_hash_shape():
    frames = extract_trace_frames("#0 /var/www/wp-content/plugins/woo/x.php(42): do_thing()")
    assert ("/var/www/wp-content/plugins/woo/x.php", 42) in frames


def test_extract_trace_frames_on_line_shape():
    frames = extract_trace_frames("PHP Fatal error thrown in /srv/site/wp-content/plugins/p/y.php on line 88")
    assert ("/srv/site/wp-content/plugins/p/y.php", 88) in frames


def test_extract_trace_frames_junk_empty():
    assert extract_trace_frames("nothing here") == []
    assert extract_trace_frames("") == []


def test_diagnosis_confirmed_grounded_only():
    assert diagnosis_confirmed("VERDICT: grounded\ngrounding: real path") is True
    assert diagnosis_confirmed("VERDICT: ungrounded") is False
    assert diagnosis_confirmed("VERDICT: grounded-ish") is False
    assert diagnosis_confirmed("no verdict here") is False
    assert diagnosis_confirmed("") is False


def test_parse_hypotheses_blocks():
    text = (
        "### HYPOTHESIS\n"
        "class: conflict\n"
        "claim: plugin X redeclares a function\n"
        "evidence: Cannot redeclare seen in debug.log\n"
        "candidate_files: wp-content/plugins/x/x.php\n"
        "confidence: high\n"
        "### END\n"
        "garbage with no end marker"
    )
    hyps = parse_hypotheses(text)
    assert len(hyps) == 1
    assert hyps[0].issue_class == "conflict"
    assert hyps[0].confidence == "high"


def test_parse_hypotheses_drops_blocks_without_claim():
    text = "### HYPOTHESIS\nclass: bug\n### END"
    assert parse_hypotheses(text) == []


def test_synthesize_no_survivors():
    out = synthesize_diagnosis([])
    assert "insufficient evidence" in out.lower()


def test_synthesize_ranks_by_confidence():
    hyps = [
        Hypothesis("config", "low one", ("e",), (), "low"),
        Hypothesis("conflict", "high one", ("e1", "e2"), ("f.php",), "high"),
    ]
    out = synthesize_diagnosis(hyps)
    # the high-confidence hypothesis is the primary class
    assert out.index("conflict") < out.index("config")


def test_render_diagnosis_plain():
    diag = Diagnosis(
        issue_class="conflict", confidence="high",
        root_cause="plugin X redeclares foo()",
        candidate_files=("wp-content/plugins/x/x.php",),
        evidence=("Cannot redeclare in debug.log",),
        recommended_next_step="remediate: deconflict or report to plugin X",
        alternatives=("config",),
    )
    out = render_diagnosis(diag)
    assert "conflict" in out
    assert "wp-content/plugins/x/x.php" in out
    assert "—" not in out


def _grounded_block(cls="conflict", claim="plugin X redeclares foo()"):
    return (
        f"### HYPOTHESIS\nclass: {cls}\nclaim: {claim}\n"
        f"evidence: Cannot redeclare in debug.log\n"
        f"candidate_files: wp-content/plugins/x/x.php\nconfidence: high\n### END"
    )


def test_run_diagnosis_keeps_grounded_drops_ungrounded():
    calls = {"n": 0}

    def fake_run_children(specs):
        calls["n"] += 1
        if calls["n"] == 1:
            # Stage 1: one explorer per lens; only the first returns a hypothesis.
            out = [(s["label"], "") for s in specs]
            out[0] = (specs[0]["label"], _grounded_block())
            return out
        # Stage 2: verify wave — confirm the single hypothesis.
        return [(s["label"], "VERDICT: grounded\ngrounding: confirmed") for s in specs]

    result = run_diagnosis("context", "evidence", run_children=fake_run_children)
    assert "conflict" in result
    assert calls["n"] == 2  # fan-out wave + verify wave


def test_run_diagnosis_drops_when_verifier_refutes():
    def fake_run_children(specs):
        # Distinguish the two waves by prompt content: only the verify prompt
        # contains "REFUTE". Verify wave -> ungrounded (refuted); fan-out wave ->
        # one grounded hypothesis block.
        if specs and "REFUTE" in specs[0]["prompt"]:
            return [(s["label"], "VERDICT: ungrounded") for s in specs]
        out = [(s["label"], "") for s in specs]
        out[0] = (specs[0]["label"], _grounded_block())
        return out

    result = run_diagnosis("context", "evidence", run_children=fake_run_children)
    assert "insufficient evidence" in result.lower()


def test_run_diagnosis_no_hypotheses_short_circuits():
    waves = {"n": 0}

    def fake_run_children(specs):
        waves["n"] += 1
        return [(s["label"], "") for s in specs]

    result = run_diagnosis("ctx", "ev", run_children=fake_run_children)
    assert "insufficient evidence" in result.lower()
    assert waves["n"] == 1  # no verify wave when nothing parsed


def test_lenses_cover_core_classes():
    labels = {label for label, _ in DIAGNOSIS_LENSES}
    assert {"conflict", "config", "environment"} <= labels
