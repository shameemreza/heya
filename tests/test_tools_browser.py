import pytest

from heya.tools_browser import BrowserSession
from heya.tools_files import ToolError


def test_navigate_without_playwright_gives_install_hint(monkeypatch):
    def boom():
        raise ImportError("no playwright")
    monkeypatch.setattr("heya.tools_browser._import_playwright", boom)
    session = BrowserSession()
    with pytest.raises(ToolError) as exc:
        session.navigate("https://example.com")
    assert "playwright" in str(exc.value).lower()


def test_snapshot_before_navigate_errors():
    session = BrowserSession()
    with pytest.raises(ToolError):
        session.snapshot()


def test_evidence_formats_captured_messages():
    session = BrowserSession()
    session._console.append("[error] boom")
    session._network.append("404 https://x/missing")
    out = session.evidence()
    assert "boom" in out and "404 https://x/missing" in out


def test_evidence_empty_is_clear():
    out = BrowserSession().evidence()
    assert "(none)" in out


# --- Real-browser behavior (needs: pip install playwright && playwright install chromium) ---

PAGE = "data:text/html,<title>Hi</title><body><h1>Hello Heya</h1><script>console.log('evi-marker')</script></body>"


@pytest.mark.integration
def test_navigate_and_snapshot_real():
    session = BrowserSession()
    try:
        text = session.navigate(PAGE)
        assert "Hello Heya" in text
        assert "Hi" in text  # title
    finally:
        session.close()


@pytest.mark.integration
def test_console_is_captured_real():
    session = BrowserSession()
    try:
        session.navigate(PAGE)
        assert "evi-marker" in session.evidence()
    finally:
        session.close()


def test_click_before_navigate_errors():
    with pytest.raises(ToolError):
        BrowserSession().click("Submit")


def test_type_before_navigate_errors():
    with pytest.raises(ToolError):
        BrowserSession().type_text("Email", "x@y.com")


FORM = (
    "data:text/html,<title>F</title><body>"
    "<input aria-label='Name'>"
    "<button onclick=\"document.querySelector('h1')?document.querySelector('h1').remove():document.body.insertAdjacentHTML('beforeend','<h1>Clicked</h1>')\">Go</button>"
    "</body>"
)


@pytest.mark.integration
def test_click_changes_page_real():
    session = BrowserSession()
    try:
        session.navigate(FORM)
        out = session.click("Go")
        assert "Clicked" in out
    finally:
        session.close()


@pytest.mark.integration
def test_type_fills_input_real():
    session = BrowserSession()
    try:
        session.navigate(FORM)
        session.type_text("Name", "Heya")
        value = session._require_page().get_by_label("Name").input_value()
        assert value == "Heya"
    finally:
        session.close()


@pytest.mark.integration
def test_screenshot_writes_png_real(tmp_path):
    session = BrowserSession()
    try:
        session.navigate(FORM)
        target = tmp_path / "shot.png"
        out = session.screenshot(target)
        assert target.exists() and target.stat().st_size > 0
        assert str(target) in out
    finally:
        session.close()
