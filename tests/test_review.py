from heya.review import (
    Finding, parse_findings, synthesize, normalize_severity, SEVERITIES, git_diff,
    run_review, verifier_confirms, REVIEWER_PROMPT, VERIFIER_PROMPT,
    WP_SECURITY_METHODOLOGY, WP_STANDARDS_METHODOLOGY,
)


def test_normalize_severity():
    assert normalize_severity("blocker") == "Blocker"
    assert normalize_severity("HIGH") == "High"
    assert normalize_severity("whatever") == "Medium"  # unknown → Medium


def test_parse_one_finding():
    text = (
        "### FINDING\n"
        "file: auth.php\n"
        "line: 88\n"
        "severity: High\n"
        "category: security\n"
        "title: Missing nonce check\n"
        "evidence: handle_save uses $_POST with no wp_verify_nonce\n"
        "suggestion: add check_admin_referer\n"
        "### END\n"
    )
    fs = parse_findings(text)
    assert len(fs) == 1
    f = fs[0]
    assert f.file == "auth.php" and f.line == 88 and f.severity == "High"
    assert f.category == "security" and "nonce" in f.title.lower()


def test_parse_no_findings_sentinel():
    assert parse_findings("NO FINDINGS") == []
    assert parse_findings("") == []


def test_parse_skips_malformed_block():
    text = "### FINDING\ngarbage with no fields\n### END\n### FINDING\nfile: a.py\ntitle: real\n### END\n"
    fs = parse_findings(text)
    # the malformed one (no file/title) is skipped; the real one survives
    assert len(fs) == 1
    assert fs[0].file == "a.py"


def test_synthesize_empty_says_nothing_blocks():
    out = synthesize([])
    assert "nothing blocks" in out.lower()


def test_synthesize_sorts_by_severity_and_collapses_nits():
    findings = [
        Finding("a.py", 1, "Nit", "style", "trailing space", "", ""),
        Finding("b.php", 9, "Blocker", "security", "SQL injection", "ev", "use prepare"),
        Finding("c.js", 3, "Medium", "bug", "off by one", "", ""),
    ]
    out = synthesize(findings)
    assert out.index("Blocker") < out.index("Medium")  # severity order
    assert "SQL injection" in out
    assert "1 nit" in out.lower() or "nit (1)" in out.lower()  # nits collapsed to a count


def test_synthesize_dedupes():
    f = Finding("a.py", 5, "High", "bug", "same bug", "", "")
    out = synthesize([f, f])
    assert out.count("same bug") == 1


def test_parse_non_integer_line_degrades_to_none():
    # A non-integer line must degrade to None, not raise.
    text = (
        "### FINDING\n"
        "file: a.py\n"
        "line: not-a-number\n"
        "severity: High\n"
        "title: bad line value\n"
        "### END\n"
    )
    fs = parse_findings(text)
    assert len(fs) == 1
    assert fs[0].line is None       # degraded, did not raise
    assert fs[0].file == "a.py"
    assert fs[0].title == "bad line value"


def _fake_runner(script):
    calls = []
    def runner(argv, cwd):
        calls.append(argv)
        return script.pop(0)
    runner.calls = calls
    return runner


def test_git_diff_branch_uses_merge_base(tmp_path):
    runner = _fake_runner([
        (0, "abc123\n", ""),            # merge-base
        (0, "diff --git a/x b/x\n+new\n", ""),  # diff
    ])
    out = git_diff("branch", allowed_roots=[tmp_path], cwd=tmp_path, runner=runner)
    assert "diff --git" in out
    assert any("merge-base" in argv for argv in runner.calls)
    assert any("abc123" in argv for argv in runner.calls)  # diff uses the merge-base


def test_git_diff_staged(tmp_path):
    runner = _fake_runner([(0, "diff --git a/y b/y\n+staged\n", "")])
    out = git_diff("staged", allowed_roots=[tmp_path], cwd=tmp_path, runner=runner)
    assert "staged" in out
    assert any("--cached" in argv for argv in runner.calls)


def test_git_diff_empty_is_clean_message(tmp_path):
    runner = _fake_runner([(0, "abc\n", ""), (0, "", "")])  # empty diff
    out = git_diff("branch", allowed_roots=[tmp_path], cwd=tmp_path, runner=runner)
    assert "nothing to review" in out.lower()


def test_git_diff_not_a_repo(tmp_path):
    runner = _fake_runner([
        (128, "", "fatal: not a git repository"),
        (128, "", "fatal: not a git repository"),
        (128, "", "fatal: not a git repository"),
    ])
    out = git_diff("branch", allowed_roots=[tmp_path], cwd=tmp_path, runner=runner)
    assert "not a git repository" in out.lower()


def test_git_diff_path_target(tmp_path):
    target = tmp_path / "foo.py"
    runner = _fake_runner([(0, "diff --git a/foo.py b/foo.py\n+x\n", "")])
    out = git_diff(str(target), allowed_roots=[tmp_path], cwd=tmp_path, runner=runner)
    assert "diff --git" in out
    # the path-target branch runs `git diff -- <path>` with the resolved path
    assert any("foo.py" in " ".join(argv) for argv in runner.calls)
    assert any("--" in argv for argv in runner.calls)


def test_verifier_confirms():
    assert verifier_confirms("VERDICT: real\ngrounding: source->sink confirmed") is True
    assert verifier_confirms("VERDICT: false-positive\ngrounding: guarded") is False
    assert verifier_confirms("unclear waffle") is False  # fail-closed → drop


def test_verifier_confirms_requires_exact_real():
    assert verifier_confirms("VERDICT: real\ngrounding: ok") is True
    assert verifier_confirms("VERDICT: realistic but guarded") is False
    assert verifier_confirms("VERDICT: really a false positive") is False
    assert verifier_confirms("VERDICT: false-positive") is False


def test_reviewer_prompt_includes_diff_and_standards():
    p = REVIEWER_PROMPT("DIFFTEXT", "correctness", "code-review", "- prefer early return")
    assert "DIFFTEXT" in p
    assert "code-review" in p           # told to read the guidance
    assert "prefer early return" in p   # the user's standards injected
    assert "### FINDING" in p           # the output contract


def test_run_review_verifies_and_drops_spurious():
    # The reviewer reports two findings; the verifier confirms the first, refutes
    # the second. Only the confirmed one survives into the verdict.
    reviewer_report = (
        "### FINDING\nfile: a.php\nline: 5\nseverity: High\ncategory: security\n"
        "title: real sqli\nevidence: $wpdb->query($_GET)\nsuggestion: prepare\n### END\n"
        "### FINDING\nfile: b.php\nline: 9\nseverity: High\ncategory: security\n"
        "title: spurious xss\nevidence: maybe\nsuggestion: escape\n### END\n"
    )
    # run_children is called twice: once for reviewers, once for verifiers.
    calls = {"n": 0}
    def fake_run_children(specs):
        calls["n"] += 1
        if calls["n"] == 1:  # reviewer fan-out
            return [("code-reviewer", reviewer_report)]
        # verifier fan-out: confirm the first finding, refute the second
        verdicts = []
        for spec in specs:
            if "real sqli" in spec["prompt"]:
                verdicts.append(("verify", "VERDICT: real\ngrounding: $_GET into query"))
            else:
                verdicts.append(("verify", "VERDICT: false-positive\ngrounding: output is escaped"))
        return verdicts

    out = run_review(
        "branch",
        run_children=fake_run_children,
        git_diff_fn=lambda t: "diff --git a/a.php b/a.php\n+bad\n",
        reviewers=[("code-reviewer", "correctness and quality", "code-review")],
    )
    assert "real sqli" in out
    assert "spurious xss" not in out  # refuted → dropped
    assert calls["n"] == 2            # verify pass ran


def test_run_review_clean_diff_says_nothing_blocks():
    def fake_run_children(specs):
        return [("code-reviewer", "NO FINDINGS")]
    out = run_review(
        "branch",
        run_children=fake_run_children,
        git_diff_fn=lambda t: "diff --git a/a.php b/a.php\n+ok\n",
        reviewers=[("code-reviewer", "correctness and quality", "code-review")],
    )
    assert "nothing blocks" in out.lower()


def test_run_review_empty_diff_short_circuits():
    out = run_review(
        "branch",
        run_children=lambda specs: [("x", "should not be called")],
        git_diff_fn=lambda t: "Nothing to review — the diff is empty.",
        reviewers=[("code-reviewer", "correctness and quality", "code-review")],
    )
    assert "nothing to review" in out.lower()


def test_run_review_caps_verification_by_severity():
    # With more findings than verify_cap, only the top-severity ones are verified;
    # lower-severity findings beyond the cap never reach the verdict.
    blocks = []
    # 3 Blocker findings + 3 Nit findings
    for i in range(3):
        blocks.append(
            f"### FINDING\nfile: b{i}.py\nline: {i}\nseverity: Blocker\n"
            f"category: bug\ntitle: blocker {i}\nevidence: e\nsuggestion: s\n### END\n")
    for i in range(3):
        blocks.append(
            f"### FINDING\nfile: n{i}.py\nline: {i}\nseverity: Nit\n"
            f"category: style\ntitle: nit {i}\nevidence: e\nsuggestion: s\n### END\n")
    reviewer_report = "".join(blocks)

    verified = []
    def fake_run_children(specs):
        if any("adversarial verifier" not in s["prompt"] for s in specs):
            return [("code-reviewer", reviewer_report)]  # reviewer fan-out
        # verifier fan-out: record which findings were verified, confirm all
        for s in specs:
            verified.append(s["prompt"])
        return [("verify", "VERDICT: real\ngrounding: ok") for _ in specs]

    out = run_review(
        "branch",
        run_children=fake_run_children,
        git_diff_fn=lambda t: "diff --git a/b0.py b/b0.py\n+x\n",
        reviewers=[("code-reviewer", "correctness", "code-review")],
        verify_cap=3,
    )
    # only 3 findings (the Blockers, top severity) were sent to verification
    assert len(verified) == 3
    assert all("blocker" in p.lower() for p in verified)
    assert "blocker 0" in out
    assert "nit 0" not in out  # beyond the cap → never verified, never in verdict


def test_security_methodology_has_taint_markers():
    m = WP_SECURITY_METHODOLOGY
    for marker in ("prepare", "esc_", "wp_verify_nonce", "current_user_can", "source", "sink"):
        assert marker in m, marker
    assert "theoretical" in m.lower()        # the noise-exclusion rule
    assert "do not report" in m.lower()


def test_standards_methodology_markers():
    m = WP_STANDARDS_METHODOLOGY.lower()
    assert "text domain" in m or "internationali" in m or "i18n" in m
    assert "capabilit" in m


def test_reviewer_prompt_includes_methodology():
    p = REVIEWER_PROMPT("DIFFBODY", "security", "wp-security", "", WP_SECURITY_METHODOLOGY)
    assert "wp_verify_nonce" in p and "prepare" in p
    assert "DIFFBODY" in p
    assert "read_guidance('wp-security')" in p


def test_reviewer_prompt_empty_methodology_is_clean():
    # methodology="" must not inject any security text (10a correctness prompt unchanged)
    p = REVIEWER_PROMPT("DIFFBODY", "correctness and quality", "code-review", "")
    assert "wp_verify_nonce" not in p
    assert "taint" not in p.lower()
    # and an explicit "" matches the default
    assert p == REVIEWER_PROMPT("DIFFBODY", "correctness and quality", "code-review", "", "")


def test_run_review_accepts_3_and_4_tuples():
    captured = []
    def fake_run_children(specs):
        captured.append(specs)
        return [(s["label"], "NO FINDINGS") for s in specs]
    # 3-tuple (10a shape) still works
    run_review("branch", run_children=fake_run_children,
               git_diff_fn=lambda t: "diff --git a/x b/x\n+x\n",
               reviewers=[("code-reviewer", "correctness", "code-review")])
    # 4-tuple (10b shape): the methodology reaches the prompt
    run_review("branch", run_children=fake_run_children,
               git_diff_fn=lambda t: "diff --git a/x b/x\n+x\n",
               reviewers=[("security-reviewer", "security", "wp-security", "TAINT_MARKER")])
    assert "TAINT_MARKER" in captured[1][0]["prompt"]


def test_git_diff_falls_back_to_master(tmp_path):
    runner = _fake_runner([
        (1, "", "fatal: no main"),          # merge-base HEAD main fails
        (0, "deadbeef\n", ""),              # merge-base HEAD master succeeds
        (0, "diff --git a/x b/x\n+x\n", ""),  # diff
    ])
    out = git_diff("branch", allowed_roots=[tmp_path], cwd=tmp_path, runner=runner)
    assert "diff --git" in out
    assert any("master" in argv for argv in runner.calls)
    assert any("deadbeef" in argv for argv in runner.calls)  # diff used master's base


def test_git_diff_all_base_refs_fail(tmp_path):
    runner = _fake_runner([
        (1, "", "no main"), (1, "", "no master"), (1, "", "no origin"),
    ])
    out = git_diff("branch", allowed_roots=[tmp_path], cwd=tmp_path, runner=runner)
    assert "could not get a diff" in out.lower()
