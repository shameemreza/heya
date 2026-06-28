from heya.tools_guidance import GuidanceItem, collect_guidance, read_guidance


def _skill(dir_path, name, description, body="body text"):
    folder = dir_path / name
    folder.mkdir()
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}\n")


def test_collect_finds_skill_folders_and_loose_md(tmp_path):
    _skill(tmp_path, "writing", "How to write")
    (tmp_path / "loose.md").write_text("# Loose\nA loose note.\n")
    items = collect_guidance([tmp_path])
    assert set(items) == {"writing", "loose"}
    assert isinstance(items["writing"], GuidanceItem)
    assert items["writing"].description == "How to write"


def test_collect_skips_missing_sources(tmp_path):
    items = collect_guidance([tmp_path / "nope", tmp_path])
    assert items == {}


def test_user_source_overrides_bundled_on_name_collision(tmp_path):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    bundled.mkdir()
    user.mkdir()
    _skill(bundled, "voice", "bundled voice", body="BUNDLED")
    _skill(user, "voice", "user voice", body="USER")
    items = collect_guidance([bundled, user])  # bundled first, user wins
    assert items["voice"].description == "user voice"
    assert "USER" in items["voice"].read()


def test_read_guidance_lists_when_no_name(tmp_path):
    _skill(tmp_path, "alpha", "first thing")
    _skill(tmp_path, "beta", "second thing")
    listing = read_guidance(None, sources=[tmp_path])
    assert "alpha" in listing and "first thing" in listing
    assert "beta" in listing and "second thing" in listing


def test_read_guidance_returns_named_content(tmp_path):
    _skill(tmp_path, "alpha", "first", body="THE ALPHA BODY")
    assert "THE ALPHA BODY" in read_guidance("alpha", sources=[tmp_path])


def test_read_guidance_unknown_name_is_clear(tmp_path):
    _skill(tmp_path, "alpha", "first")
    out = read_guidance("ghost", sources=[tmp_path])
    assert "ghost" in out and "alpha" in out


def test_read_guidance_empty_sources(tmp_path):
    assert "No guidance" in read_guidance(None, sources=[])


def test_description_falls_back_to_first_real_line(tmp_path):
    (tmp_path / "note.md").write_text("# Heading\n\nThe first real line here.\n")
    items = collect_guidance([tmp_path])
    assert items["note"].description == "The first real line here."


def test_malformed_utf8_file_does_not_crash_collection(tmp_path):
    _skill(tmp_path, "good", "a good one")
    (tmp_path / "bad.md").write_bytes(b"# Note\n\xff\xfe not valid utf-8\n")
    items = collect_guidance([tmp_path])  # must not raise
    assert "good" in items and "bad" in items
    assert items["bad"].read()  # readable via errors="replace"


from heya.tools_guidance import BUNDLED_GUIDANCE_DIR


def test_bundled_guidance_is_discoverable():
    items = collect_guidance([BUNDLED_GUIDANCE_DIR])
    assert "writing-voice" in items
    assert "code-review" in items
    assert items["writing-voice"].description  # non-empty description
    assert "voice" in items["writing-voice"].read().lower()


def test_minimal_code_guidance_is_readable():
    from heya.tools_guidance import read_guidance, BUNDLED_GUIDANCE_DIR
    text = read_guidance("minimal-code", sources=[BUNDLED_GUIDANCE_DIR])
    # the ladder and the safety carve-out are both present
    assert "ladder" in text.lower()
    assert "never minimize" in text.lower()
    assert "stay in scope" in text.lower()  # no unrelated edits while fixing
    # no em dashes in the bundled copy
    assert "—" not in text


def test_environment_guidance_is_readable():
    from heya.tools_guidance import read_guidance, BUNDLED_GUIDANCE_DIR
    text = read_guidance("environment", sources=[BUNDLED_GUIDANCE_DIR])
    assert "do not assume" in text.lower() or "check, do not guess" in text.lower()
    assert "uname" in text and "version" in text.lower()
    assert "—" not in text
