from heya.agent_defs import discover_agent_roles, agent_roles_note


def _agent(d, name, frontmatter, body="You review code."):
    (d / f"{name}.md").write_text(f"---\n{frontmatter}\n---\n{body}")


def test_discover_agent_roles(tmp_path):
    _agent(tmp_path, "sec", "name: sec\ndescription: security reviewer\ntools: Read, Grep",
           "You are a security reviewer.")
    roles = discover_agent_roles([tmp_path])
    assert "sec" in roles
    assert "security reviewer" in roles["sec"].system_addendum or "You are a security" in roles["sec"].system_addendum
    assert roles["sec"].tools == frozenset({"read_file", "search_files"})  # alias-translated


def test_discover_agent_roles_no_tools_is_none(tmp_path):
    _agent(tmp_path, "gen", "name: gen\ndescription: general", "Do general work.")
    roles = discover_agent_roles([tmp_path])
    assert roles["gen"].tools is None  # inherit full toolbox


def test_discover_agent_roles_skips_missing_and_malformed(tmp_path):
    _agent(tmp_path, "ok", "name: ok\ndescription: fine")
    (tmp_path / "bad.md").write_text("no frontmatter here")  # stem fallback, still a role
    roles = discover_agent_roles([tmp_path, tmp_path / "nope"])
    assert "ok" in roles and "bad" in roles


def test_agent_roles_note(tmp_path):
    _agent(tmp_path, "sec", "name: sec\ndescription: d", "Security reviewer agent.")
    roles = discover_agent_roles([tmp_path])
    note = agent_roles_note(roles)
    assert "sec" in note and "spawn_agent" in note
    assert agent_roles_note({}) == ""


def test_discover_agent_roles_wildcard_tools_is_none(tmp_path):
    (tmp_path / "all.md").write_text("---\nname: all\ndescription: d\ntools: '*'\n---\nDo anything.")
    roles = discover_agent_roles([tmp_path])
    assert roles["all"].tools is None  # '*' means inherit full toolbox, not zero tools


def test_agent_roles_note_caps_total(tmp_path):
    for i in range(60):
        (tmp_path / f"a{i:03d}.md").write_text(f"---\nname: a{i:03d}\ndescription: d\n---\nbody")
    roles = discover_agent_roles([tmp_path])
    note = agent_roles_note(roles)
    assert note.count("\n- a") <= 50          # capped, not all 60 listed
    assert "more" in note                      # a truncation note is present
