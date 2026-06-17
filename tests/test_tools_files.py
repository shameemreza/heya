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
