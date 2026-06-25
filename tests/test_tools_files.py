import pytest

from heya.tools_files import (
    CommandResult,
    ToolError,
    read_file,
    resolve_in_allowlist,
    run_command,
    write_file,
)


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


def test_write_file_creates_and_returns_byte_count(tmp_path):
    target = tmp_path / "out.txt"
    n = write_file(target, "data", allowed_roots=[tmp_path])
    assert target.read_text() == "data"
    assert n == 4


def test_write_file_creates_missing_parent_dirs(tmp_path):
    target = tmp_path / "deep" / "nested" / "out.txt"
    write_file(target, "ok", allowed_roots=[tmp_path])
    assert target.read_text() == "ok"


def test_write_file_overwrites_existing(tmp_path):
    target = tmp_path / "out.txt"
    target.write_text("old")
    write_file(target, "new", allowed_roots=[tmp_path])
    assert target.read_text() == "new"


def test_write_file_denies_outside_root(tmp_path):
    outside = tmp_path.parent / "escape.txt"
    with pytest.raises(ToolError):
        write_file(outside, "data", allowed_roots=[tmp_path])


def test_write_file_denies_before_creating_dirs(tmp_path):
    # Outside-root write must be refused before any directory is created.
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "elsewhere" / "deep" / "out.txt"
    with pytest.raises(ToolError):
        write_file(outside, "data", allowed_roots=[root])
    assert not (tmp_path / "elsewhere").exists()


def test_run_command_captures_stdout_and_exit_zero(tmp_path):
    result = run_command("echo hi", cwd=tmp_path, allowed_roots=[tmp_path], timeout=10)
    assert isinstance(result, CommandResult)
    assert result.stdout.strip() == "hi"
    assert result.exit_code == 0


def test_run_command_captures_nonzero_exit_and_stderr(tmp_path):
    result = run_command(
        "echo oops 1>&2; exit 3", cwd=tmp_path, allowed_roots=[tmp_path], timeout=10
    )
    assert result.exit_code == 3
    assert "oops" in result.stderr


def test_run_command_runs_in_given_cwd(tmp_path):
    (tmp_path / "marker.txt").write_text("here")
    result = run_command("ls", cwd=tmp_path, allowed_roots=[tmp_path], timeout=10)
    assert "marker.txt" in result.stdout


def test_run_command_denies_cwd_outside_root(tmp_path):
    with pytest.raises(ToolError):
        run_command("echo hi", cwd=tmp_path.parent, allowed_roots=[tmp_path], timeout=10)


def test_run_command_times_out(tmp_path):
    with pytest.raises(ToolError):
        run_command("sleep 5", cwd=tmp_path, allowed_roots=[tmp_path], timeout=0.3)


def test_search_files_finds_matches(tmp_path):
    from heya.tools_files import search_files
    (tmp_path / "a.py").write_text("alpha\nbeta nonce_check\ngamma\n")
    (tmp_path / "b.py").write_text("delta\n")
    out = search_files("nonce_check", allowed_roots=[tmp_path], cwd=tmp_path)
    assert "a.py:2:" in out
    assert "nonce_check" in out
    assert "b.py" not in out


def test_search_files_no_match(tmp_path):
    from heya.tools_files import search_files
    (tmp_path / "a.py").write_text("alpha\n")
    out = search_files("zzz", allowed_roots=[tmp_path], cwd=tmp_path)
    assert "no matches" in out.lower()


def test_search_files_confined_to_allowlist(tmp_path):
    from heya.tools_files import search_files
    (tmp_path / "a.py").write_text("hit\n")
    with pytest.raises(ToolError):
        search_files("hit", allowed_roots=[tmp_path], cwd=tmp_path, path="/etc")


def test_search_files_caps_results(tmp_path):
    from heya.tools_files import search_files
    (tmp_path / "big.txt").write_text("hit\n" * 500)
    out = search_files("hit", allowed_roots=[tmp_path], cwd=tmp_path, max_results=10)
    assert out.count("big.txt:") <= 10
    assert "truncated" in out.lower()
