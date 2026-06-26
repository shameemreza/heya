from pathlib import Path

from heya.skills import (
    SkillItem, parse_skill_frontmatter, collect_skills, build_skills_block,
    render_skill, translate_allowed_tools,
)


def _write_skill(d: Path, name: str, frontmatter: str, body: str = "Body here."):
    sd = d / name
    sd.mkdir(parents=True)
    (sd / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}\n")
    return sd


def test_parse_frontmatter_fields():
    fm = parse_skill_frontmatter(
        "---\nname: foo\ndescription: does foo\nwhen_to_use: when fooing\n"
        "allowed-tools: Read, Edit, Bash\n---\nbody")
    assert fm["name"] == "foo"
    assert fm["description"] == "does foo"
    assert fm["when_to_use"] == "when fooing"
    assert fm["allowed_tools"] == ("Read", "Edit", "Bash")


def test_parse_frontmatter_space_delimited_tools():
    fm = parse_skill_frontmatter("---\nname: x\nallowed-tools: Read Bash\n---\nb")
    assert fm["allowed_tools"] == ("Read", "Bash")


def test_parse_frontmatter_missing():
    assert parse_skill_frontmatter("no frontmatter")["name"] == ""


def test_translate_allowed_tools():
    assert translate_allowed_tools(("Read", "Edit", "Bash", "Grep")) == (
        "read_file", "write_file", "run_command", "search_files")
    # unknown passed through; duplicates collapsed
    assert translate_allowed_tools(("Read", "Read", "custom_tool")) == (
        "read_file", "custom_tool")


def test_collect_skills_finds_and_overrides(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    _write_skill(a, "alpha", "name: alpha\ndescription: from a")
    _write_skill(b, "alpha", "name: alpha\ndescription: from b")  # later dir wins
    _write_skill(a, "beta", "name: beta\ndescription: bee")
    skills = collect_skills([a, b])
    assert set(skills) == {"alpha", "beta"}
    assert skills["alpha"].description == "from b"


def test_collect_skills_skips_malformed_and_missing(tmp_path):
    d = tmp_path / "d"
    (d / "no-skill-md").mkdir(parents=True)  # dir without SKILL.md
    _write_skill(d, "ok", "name: ok\ndescription: fine")
    # malformed frontmatter -> still collected, name falls back to dir name
    bad = d / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text("not real frontmatter")
    skills = collect_skills([d, tmp_path / "does-not-exist"])
    assert "ok" in skills
    assert "bad" in skills  # dir-name fallback, never crashes


def test_build_skills_block_lists_and_bounds():
    items = {
        "alpha": SkillItem("alpha", "does alpha", "", Path("/x/alpha"), (), Path("/x/alpha/SKILL.md")),
    }
    block = build_skills_block(items)
    assert "alpha: does alpha" in block
    assert "Skill(" in block
    assert build_skills_block({}) == ""


def test_render_skill_substitutes(tmp_path):
    sd = _write_skill(tmp_path, "greet",
                      "name: greet\ndescription: greet",
                      "Hello $ARGUMENTS from ${CLAUDE_SKILL_DIR}. First=$0 Second=$1")
    skills = collect_skills([tmp_path])
    out = render_skill(skills["greet"], "world there")
    assert "Hello world there from" in out
    assert str((tmp_path / "greet")) in out
    assert "First=world Second=there" in out
    assert "---" not in out  # frontmatter stripped


def test_render_skill_does_not_execute_shell(tmp_path):
    _write_skill(tmp_path, "danger", "name: danger\ndescription: d",
                 "Run !`rm -rf /` please")
    skills = collect_skills([tmp_path])
    out = render_skill(skills["danger"])
    assert "!`rm -rf /`" in out  # left literal, never executed
