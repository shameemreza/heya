from heya.project import load_project_instructions


def test_reads_agents_md(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# Build\nRun make test before committing.")
    out = load_project_instructions(tmp_path)
    assert "Run make test" in out and "AGENTS.md" in out
    assert "do not override" in out.lower()


def test_reads_both_agents_and_claude(tmp_path):
    (tmp_path / "AGENTS.md").write_text("agents content")
    (tmp_path / "CLAUDE.md").write_text("claude content")
    out = load_project_instructions(tmp_path)
    assert "agents content" in out and "claude content" in out


def test_walks_up_to_find(tmp_path):
    (tmp_path / "AGENTS.md").write_text("root rules")
    sub = tmp_path / "src" / "deep"
    sub.mkdir(parents=True)
    assert "root rules" in load_project_instructions(sub)


def test_stops_at_git_root(tmp_path):
    (tmp_path / "AGENTS.md").write_text("outside the repo")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    sub = repo / "src"
    sub.mkdir()
    assert "outside the repo" not in load_project_instructions(sub)


def test_disabled_returns_empty(tmp_path):
    (tmp_path / "AGENTS.md").write_text("rules")
    assert load_project_instructions(tmp_path, enabled=False) == ""


def test_none_when_absent(tmp_path):
    assert load_project_instructions(tmp_path) == ""


def test_caps_large_file(tmp_path):
    (tmp_path / "AGENTS.md").write_text("x" * 50000)
    assert len(load_project_instructions(tmp_path)) < 20000
