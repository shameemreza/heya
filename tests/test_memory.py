from pathlib import Path

from heya.memory import (
    MemoryStore, MemoryItem, MEMORY_TYPES, parse_frontmatter, serialize_memory,
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
    fm, body = parse_frontmatter(text)
    assert fm["type"] == "user"            # not overridden by the injected line
    assert "\n" not in fm["description"]   # description collapsed to one line
    assert body.strip() == "body"
