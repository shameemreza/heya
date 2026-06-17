import pytest

from heya.tools_files import ToolError, resolve_in_allowlist


def test_resolves_path_inside_root(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    assert resolve_in_allowlist(f, [tmp_path]) == f.resolve()


def test_resolves_not_yet_existing_target_inside_root(tmp_path):
    target = tmp_path / "sub" / "new.txt"
    (tmp_path / "sub").mkdir()
    assert resolve_in_allowlist(target, [tmp_path]) == target.resolve()


def test_rejects_path_outside_all_roots(tmp_path):
    outside = tmp_path.parent / "elsewhere.txt"
    with pytest.raises(ToolError):
        resolve_in_allowlist(outside, [tmp_path])


def test_rejects_parent_traversal(tmp_path):
    sneaky = tmp_path / ".." / "escape.txt"
    with pytest.raises(ToolError):
        resolve_in_allowlist(sneaky, [tmp_path])


def test_rejects_symlink_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("nope")
    link = root / "link.txt"
    link.symlink_to(secret)
    with pytest.raises(ToolError):
        resolve_in_allowlist(link, [root])


def test_rejects_when_no_roots(tmp_path):
    with pytest.raises(ToolError):
        resolve_in_allowlist(tmp_path / "a.txt", [])


def test_rejects_sibling_prefix_root(tmp_path):
    # /foo must not accept /foobar — guards against string-prefix matching.
    root = tmp_path / "foo"
    root.mkdir()
    sibling = tmp_path / "foobar"
    sibling.mkdir()
    with pytest.raises(ToolError):
        resolve_in_allowlist(sibling / "x.txt", [root])


def test_accepts_under_any_of_multiple_roots(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    target = root_b / "file.txt"
    assert resolve_in_allowlist(target, [root_a, root_b]) == target.resolve()


from heya.tools_files import read_file


def test_read_file_returns_text_inside_root(tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("hello heya")
    assert read_file(f, allowed_roots=[tmp_path]) == "hello heya"


def test_read_file_denies_outside_root(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    with pytest.raises(ToolError):
        read_file(outside, allowed_roots=[tmp_path])


def test_read_file_missing_raises_tool_error(tmp_path):
    with pytest.raises(ToolError):
        read_file(tmp_path / "ghost.txt", allowed_roots=[tmp_path])
