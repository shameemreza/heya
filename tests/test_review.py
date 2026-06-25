from heya.review import Finding, parse_findings, synthesize, normalize_severity, SEVERITIES, git_diff


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
    runner = _fake_runner([(128, "", "fatal: not a git repository")])
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
