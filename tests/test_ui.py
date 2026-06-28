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
