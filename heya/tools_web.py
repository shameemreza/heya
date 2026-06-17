"""Web tools: fetch a page as readable text, and search the web.

web_fetch GETs a URL (http/https only) and returns extracted text — scripts, nav,
and boilerplate removed — length-capped. web_search goes through a pluggable
SearchProvider. Both raise ToolError on failure so the agent loop turns it into a
recoverable string; both are reads (auto-approved). Note: a fetch URL and a search
query both leave the machine.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from .config import ConfigError, SearchConfig
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


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


def _ddg_unwrap(href: str) -> str:
    """DuckDuckGo wraps real URLs in /l/?uddg=<encoded>; return the real one."""
    parsed = urlparse(href)
    qs = parse_qs(parsed.query)
    if "uddg" in qs:
        return unquote(qs["uddg"][0])
    if href.startswith("//"):
        return "https:" + href
    return href


class DuckDuckGoSearch:
    """Keyless search by scraping the DuckDuckGo HTML endpoint."""

    URL = "https://html.duckduckgo.com/html/"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=20, headers={"User-Agent": _USER_AGENT})
        try:
            resp = client.post(self.URL, data={"q": query})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ToolError(f"DuckDuckGo search failed: {exc}") from exc
        finally:
            if owns:
                client.close()
        soup = BeautifulSoup(resp.text, "html.parser")
        results: list[SearchResult] = []
        for anchor in soup.select("a.result__a"):
            container = anchor.find_parent(class_="result") or anchor.parent
            snippet_el = container.select_one(".result__snippet") if container else None
            results.append(
                SearchResult(
                    title=anchor.get_text(" ", strip=True),
                    url=_ddg_unwrap(anchor.get("href", "")),
                    snippet=snippet_el.get_text(" ", strip=True) if snippet_el else "",
                )
            )
            if len(results) >= max_results:
                break
        return results


class BraveSearch:
    URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str | None, *, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self._api_key:
            raise ToolError("Brave search needs an API key; set the env var named in [search].api_key_env.")
        owns = self._client is None
        client = self._client or httpx.Client(timeout=20)
        try:
            resp = client.get(
                self.URL,
                params={"q": query, "count": max_results},
                headers={"X-Subscription-Token": self._api_key, "Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise ToolError(f"Brave search failed: {exc}") from exc
        finally:
            if owns:
                client.close()
        items = (data.get("web") or {}).get("results") or []
        return [
            SearchResult(title=i.get("title", ""), url=i.get("url", ""), snippet=i.get("description", ""))
            for i in items[:max_results]
        ]


class TavilySearch:
    URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str | None, *, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self._api_key:
            raise ToolError("Tavily search needs an API key; set the env var named in [search].api_key_env.")
        owns = self._client is None
        client = self._client or httpx.Client(timeout=20)
        try:
            resp = client.post(
                self.URL,
                json={"api_key": self._api_key, "query": query, "max_results": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise ToolError(f"Tavily search failed: {exc}") from exc
        finally:
            if owns:
                client.close()
        items = data.get("results") or []
        return [
            SearchResult(title=i.get("title", ""), url=i.get("url", ""), snippet=i.get("content", ""))
            for i in items[:max_results]
        ]


def build_search_provider(config: SearchConfig, *, client: httpx.Client | None = None):
    """Construct the search provider named by config (key read from its env var)."""
    if config.provider == "duckduckgo":
        return DuckDuckGoSearch(client=client)
    if config.provider == "brave":
        return BraveSearch(config.api_key, client=client)
    if config.provider == "tavily":
        return TavilySearch(config.api_key, client=client)
    raise ConfigError(f"Unknown search provider {config.provider!r}")


def web_search(query: str, *, provider, max_results: int = 5) -> str:
    """Run a search and format results as text. Raises ToolError on failure."""
    if provider is None:
        raise ToolError("web search is not configured")
    results = provider.search(query, max_results=max_results)
    if not results:
        return f"No results for {query!r}."
    blocks = [f"{i}. {r.title}\n   {r.url}\n   {r.snippet}" for i, r in enumerate(results, 1)]
    return "\n".join(blocks)
