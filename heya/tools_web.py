"""Web tools: fetch a page as readable text, and search the web.

web_fetch GETs a URL (http/https only) and returns extracted text — scripts, nav,
and boilerplate removed — length-capped. web_search goes through a pluggable
SearchProvider. Both raise ToolError on failure so the agent loop turns it into a
recoverable string; both are reads (auto-approved). Note: a fetch URL and a search
query both leave the machine.
"""
from __future__ import annotations

from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .tools_files import ToolError

DEFAULT_MAX_CHARS = 20000
_USER_AGENT = "Mozilla/5.0 (compatible; Heya/0.1)"
_STRIP_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg"]


def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    out: list[str] = []
    blank = False
    for line in lines:
        if line:
            out.append(line)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def web_fetch(
    url: str,
    *,
    timeout: float,
    client: httpx.Client | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Fetch an http/https URL and return readable text (boilerplate stripped)."""
    scheme = urlparse(url).scheme
    if scheme not in ("http", "https"):
        raise ToolError(f"web_fetch only supports http/https URLs, got {scheme or 'no'} scheme")
    owns = client is None
    client = client or httpx.Client(
        timeout=timeout, follow_redirects=True, headers={"User-Agent": _USER_AGENT}
    )
    try:
        resp = client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        text = _extract_text(resp.text) if ("html" in content_type or not content_type) else resp.text
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not fetch {url}: {exc}") from exc
    finally:
        if owns:
            client.close()
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n…[truncated at {max_chars} chars]"
    return text
