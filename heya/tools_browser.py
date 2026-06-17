"""Stateful headless browser via Playwright, for reproduction and evidence.

Chromium launches lazily on first use, so Heya runs fine without Playwright
installed — browser tools then return a clear install hint. Console messages and
failed/error responses are recorded continuously and returned on demand. The
session persists across tool calls so a login carries through a flow.
"""
from __future__ import annotations

from pathlib import Path

from .tools_files import ToolError

_INSTALL_HINT = (
    "The browser is not available. Enable it with:\n"
    "  pip install playwright && python -m playwright install chromium"
)
_MAX_TEXT = 15000


def _import_playwright():
    """Import seam so tests can simulate Playwright being absent."""
    from playwright.sync_api import sync_playwright

    return sync_playwright


class BrowserSession:
    def __init__(self, *, headless: bool = True) -> None:
        self.headless = headless
        self._pw = None
        self._browser = None
        self._page = None
        self._console: list[str] = []
        self._network: list[str] = []

    @property
    def started(self) -> bool:
        return self._page is not None

    def _ensure_page(self):
        if self._page is not None:
            return self._page
        try:
            sync_playwright = _import_playwright()
        except ImportError as exc:
            raise ToolError(_INSTALL_HINT) from exc
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=self.headless)
            page = self._browser.new_page()
        except Exception as exc:  # binary missing / launch failure
            raise ToolError(f"Could not start the browser. {_INSTALL_HINT}\n({exc})") from exc
        page.on("console", lambda msg: self._console.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: self._console.append(f"[pageerror] {err}"))
        page.on("requestfailed", lambda req: self._network.append(f"FAILED {req.url}"))
        page.on("response", lambda resp: self._note_response(resp))
        self._page = page
        return page

    def _note_response(self, resp) -> None:
        if resp.status >= 400:
            self._network.append(f"{resp.status} {resp.url}")

    def _require_page(self):
        if self._page is None:
            raise ToolError("No page is open. Use browser_navigate first.")
        return self._page

    def navigate(self, url: str) -> str:
        page = self._ensure_page()
        try:
            page.goto(url, wait_until="domcontentloaded")
        except Exception as exc:
            raise ToolError(f"Could not navigate to {url}: {exc}") from exc
        return self.snapshot()

    def snapshot(self) -> str:
        page = self._require_page()
        try:
            text = page.inner_text("body")
        except Exception:
            text = ""
        if len(text) > _MAX_TEXT:
            text = text[:_MAX_TEXT] + "\n…[truncated]"
        return f"URL: {page.url}\nTitle: {page.title()}\n\n{text}".strip()

    def evidence(self) -> str:
        console = "\n".join(self._console[-50:]) or "(none)"
        network = "\n".join(self._network[-50:]) or "(none)"
        return f"Console messages:\n{console}\n\nNetwork errors:\n{network}"

    def close(self) -> None:
        try:
            if self._browser is not None:
                self._browser.close()
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass
        self._pw = self._browser = self._page = None
