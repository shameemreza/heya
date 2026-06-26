from heya.diagnosis import (
    ISSUE_CLASSES, classify_log, extract_trace_frames, Hypothesis,
    parse_hypotheses, diagnosis_confirmed, Diagnosis, render_diagnosis,
    synthesize_diagnosis,
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
