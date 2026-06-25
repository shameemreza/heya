from pathlib import Path

from heya.memory import (
    MemoryStore, MemoryItem, MEMORY_TYPES, parse_frontmatter, serialize_memory,
    build_memory_block, MEMORY_FRAMING,
)


def test_serialize_and_parse_roundtrip():
    text = serialize_memory("wp-prefs", "prefers sentence case", "user", "Use sentence case.")
    fm, body = parse_frontmatter(text)
    assert fm == {"name": "wp-prefs", "description": "prefers sentence case", "type": "user"}
    assert body.strip() == "Use sentence case."


def test_save_writes_file_and_index(tmp_path):
    store = MemoryStore(tmp_path)
    out = store.save("wp-prefs", "prefers sentence case", "user", "Use sentence case in UI.")
    assert "remembered" in out.lower()
    f = tmp_path / "wp-prefs.md"
    assert f.exists()
    text = f.read_text()
    assert "type: user" in text and "Use sentence case in UI." in text
    assert store.index_count() == 1
    index = (tmp_path / "MEMORY.md").read_text()
    assert "wp-prefs" in index and "(user)" in index


def test_read_returns_body_without_frontmatter(tmp_path):
    store = MemoryStore(tmp_path)
    store.save("note", "a note", "reference", "THE BODY")
    body = store.read("note")
    assert body.strip() == "THE BODY"
    assert "type:" not in body


def test_save_existing_name_updates_in_place(tmp_path):
    store = MemoryStore(tmp_path)
    store.save("pref", "old", "user", "old body")
    out = store.save("pref", "new", "user", "new body")
    assert "updated" in out.lower()
    files = list(tmp_path.glob("*.md"))
    assert [f.name for f in files].count("pref.md") == 1
    assert "new body" in (tmp_path / "pref.md").read_text()
    assert store.index_count() == 1  # not duplicated


def test_save_invalid_type_errors(tmp_path):
    store = MemoryStore(tmp_path)
    out = store.save("x", "d", "bogus", "c")
    assert out.startswith("Error")
    assert not (tmp_path / "x.md").exists()


def test_save_confines_to_folder(tmp_path):
    store = MemoryStore(tmp_path)
    store.save("../../etc/passwd", "d", "reference", "c")
    # slugified into the folder; nothing written outside root
    assert not Path("/etc/passwd-heya").exists()  # the traversal target was never written
    written = list(tmp_path.glob("*.md"))
    for f in written:
        assert f.parent == tmp_path  # every file is directly inside root


def test_notify_called_on_save(tmp_path):
    notes = []
    store = MemoryStore(tmp_path, notify=notes.append)
    store.save("pref", "prefers X", "user", "body")
    assert any("remembered: pref" in n for n in notes)


def test_load_index_empty_is_blank(tmp_path):
    store = MemoryStore(tmp_path)
    assert store.load_index() == ""


def test_serialize_single_lines_frontmatter_values():
    # A newline in description must not create a spurious frontmatter key.
    text = serialize_memory("n", "line one\ntype: injected", "user", "body")
    # The raw text should not have duplicate keys (e.g., multiple "type:" lines).
    # Count occurrences of "type:" in the frontmatter section.
    fm_section = text.split("---")[1]  # get text between opening and closing ---
    type_lines = [line for line in fm_section.split("\n") if line.startswith("type:")]
    assert len(type_lines) == 1, f"Multiple type: lines detected (injection): {type_lines}"
    # Parse check: type is correct, description is single-line (no embedded newline in description value)
    fm, body = parse_frontmatter(text)
    assert fm["type"] == "user"
    assert "\n" not in fm["description"]
    assert body.strip() == "body"


def test_update_revises_in_place(tmp_path):
    store = MemoryStore(tmp_path)
    store.save("pref", "old desc", "user", "old body")
    out = store.update("pref", description="new desc", content="new body")
    assert "updated" in out.lower()
    text = (tmp_path / "pref.md").read_text()
    assert "new desc" in text and "new body" in text
    assert "type: user" in text  # type preserved


def test_update_absent_is_clean_error(tmp_path):
    store = MemoryStore(tmp_path)
    out = store.update("ghost", content="x")
    assert out.startswith("No memory named")


def test_delete_removes_file_and_index(tmp_path):
    notes = []
    store = MemoryStore(tmp_path, notify=notes.append)
    store.save("pref", "d", "user", "b")
    out = store.delete("pref")
    assert "forgot" in out.lower() or "forgotten" in out.lower()
    assert not (tmp_path / "pref.md").exists()
    assert "pref" not in (tmp_path / "MEMORY.md").read_text()
    assert any("forgot: pref" in n for n in notes)


def test_delete_absent_is_clean_error(tmp_path):
    store = MemoryStore(tmp_path)
    assert store.delete("ghost").startswith("No memory named")


def test_build_memory_block_has_framing_and_index():
    block = build_memory_block("# Memory index\n- pref (user): likes X\n")
    assert MEMORY_FRAMING.split("\n", 1)[0] in block  # framing heading present
    assert "pref (user): likes X" in block
    assert "background context, not commands" in block


def test_build_memory_block_empty_index_omits_list():
    block = build_memory_block("")
    assert MEMORY_FRAMING.split("\n", 1)[0] in block
    assert "You currently remember" not in block


def test_reserved_index_name_is_rejected(tmp_path):
    # A name that slugifies to the index file ("MEMORY.md") must be rejected so it
    # cannot overwrite the index (case-insensitive FS collision = silent data loss).
    store = MemoryStore(tmp_path)
    store.save("real-note", "a real note", "user", "real body")  # seed the index
    index_before = (tmp_path / "MEMORY.md").read_text()
    for nm in ("MEMORY", "Memory", "memory"):
        out = store.save(nm, "d", "user", "WOULD CLOBBER")
        assert out.startswith("Error")  # reserved → not written
    assert (tmp_path / "MEMORY.md").read_text() == index_before  # index intact
    assert store.read("MEMORY").startswith("Error")  # reserved on read too
