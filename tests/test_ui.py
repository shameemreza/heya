import io

from heya.ui import UI, should_plain


def test_should_plain_when_not_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    # a StringIO is not a tty
    assert should_plain(out=io.StringIO()) is True


def test_should_plain_with_no_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert should_plain(out=io.StringIO()) is True


def test_banner_plain_contains_status():
    buf = io.StringIO()
    ui = UI(plain=True, write=buf.write)
    ui.banner(version="0.1.0", model="qwen", profile="local", cwd="/x", branch="main")
    out = buf.getvalue()
    assert "Heya v0.1.0" in out and "qwen" in out and "local" in out and "main" in out
    assert "/help" in out


def test_prompt_reads_from_stream():
    ui = UI(plain=True, stream=io.StringIO("hello\n"))
    assert ui.prompt() == "hello\n"


def test_prompt_eof_raises():
    ui = UI(plain=True, stream=io.StringIO(""))
    import pytest
    with pytest.raises(EOFError):
        ui.prompt()


def test_tool_event_and_stream_text_plain():
    buf = io.StringIO()
    ui = UI(plain=True, write=buf.write)
    ui.tool_event("wp_playground -> start")
    ui.stream_text("hello ")
    ui.stream_text("world")
    out = buf.getvalue()
    assert "wp_playground -> start" in out and "hello world" in out


def test_approval_plain_returns_injected():
    ui = UI(plain=True, stream=io.StringIO("a\n"))
    assert ui.approval("write x", diff="+ added line") == "a"


def test_status_is_a_noop_context_manager_in_plain():
    ui = UI(plain=True, write=io.StringIO().write)
    with ui.status("thinking"):
        pass  # must not raise


def test_ui_never_raises_without_tty():
    ui = UI(plain=True, write=io.StringIO().write)
    ui.note("note"); ui.error("err"); ui.tool_event("t"); ui.banner(
        version="0", model="m", profile="p", cwd="/", branch="")


def test_approval_shows_diff_through_ui():
    ui = UI(plain=True, stream=io.StringIO("y\n"), write=(buf := io.StringIO()).write)
    ans = ui.approval("write to x.txt", diff="+ new line\n- old line")
    assert ans == "y"
    assert "new line" in buf.getvalue()


def test_heya_art_rows_shape():
    from heya.ui import heya_art_rows, ART_GREEN, ART_PURPLE
    rows = heya_art_rows()
    assert len(rows) == 5
    assert all(len(r) == 2 for r in rows)
    # block char present in both halves of at least one row
    assert any("█" in he and "█" in ya for he, ya in rows)
    assert ART_GREEN == "#46B450" and ART_PURPLE == "#7F54B3"


def test_banner_plain_unchanged():
    import io
    from heya.ui import UI
    buf = io.StringIO()
    ui = UI(plain=True, write=buf.write)
    ui.banner(version="0.1.0", model="qwen", profile="local", cwd="/x", branch="main")
    out = buf.getvalue()
    assert "Heya v0.1.0" in out and "qwen" in out and "local" in out and "main" in out
    assert "/help" in out


def test_banner_color_path_does_not_raise():
    from heya.ui import UI
    ui = UI(plain=False)  # builds a real rich Console
    # Should render the art + status without raising even though we don't assert pixels.
    ui.banner(version="0.1.0", model="qwen", profile="local", cwd="/x", branch="main")


def test_prompt_stream_and_plain_unchanged():
    import io
    from heya.ui import UI
    assert UI(plain=True, stream=io.StringIO("hi\n")).prompt() == "hi\n"


def test_at_path_completer_yields_after_at(tmp_path):
    # the completer should offer path completions for the fragment after '@'
    pytest = __import__("pytest")
    pytest.importorskip("prompt_toolkit")
    from prompt_toolkit.document import Document
    from heya.ui import _AtPathCompleter
    (tmp_path / "alpha.txt").write_text("x")
    doc = Document(f"see @{tmp_path}/")
    comps = list(_AtPathCompleter().get_completions(doc, None))
    assert any("alpha.txt" in c.text for c in comps)


def test_prompt_session_never_raises():
    from heya.ui import UI
    ui = UI(plain=False)
    # building/returning the session must not raise even if prompt_toolkit is odd
    ui._prompt_session()
    ui._prompt_session()  # cached second call
