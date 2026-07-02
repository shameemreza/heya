import httpx
import pytest

from heya.config import SearchConfig
from heya.tools_files import ToolError
from heya.tools_web import (
    BraveSearch,
    DuckDuckGoSearch,
    SearchResult,
    TavilySearch,
    build_search_provider,
    web_fetch,
    web_search,
)

HTML = """
<html><head><title>T</title><style>.x{color:red}</style></head>
<body>
<nav>Home About</nav>
<script>console.log('nope')</script>
<h1>Main Heading</h1>
<p>First paragraph of real content.</p>
<footer>copyright</footer>
</body></html>
"""


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_web_fetch_extracts_readable_text():
    client = _client(lambda req: httpx.Response(200, text=HTML, headers={"content-type": "text/html"}))
    out = web_fetch("https://example.com", timeout=10, client=client)
    assert "Main Heading" in out
    assert "First paragraph of real content." in out
    assert "console.log" not in out  # script stripped
    assert "color:red" not in out    # style stripped


def test_web_fetch_rejects_non_http_scheme():
    with pytest.raises(ToolError):
        web_fetch("file:///etc/passwd", timeout=10)


def test_web_fetch_raises_on_http_error():
    client = _client(lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(ToolError):
        web_fetch("https://example.com", timeout=10, client=client)


def test_web_fetch_truncates_long_pages():
    big = "<html><body>" + ("word " * 10000) + "</body></html>"
    client = _client(lambda req: httpx.Response(200, text=big, headers={"content-type": "text/html"}))
    out = web_fetch("https://example.com", timeout=10, client=client, max_chars=500)
    assert len(out) < 700
    assert "truncated" in out.lower()


def test_web_fetch_returns_non_html_as_is():
    client = _client(lambda req: httpx.Response(200, text='{"k": 1}', headers={"content-type": "application/json"}))
    out = web_fetch("https://example.com/data.json", timeout=10, client=client)
    assert '{"k": 1}' in out


DDG_HTML = """
<div class="result results_links">
  <h2 class="result__title">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&amp;rut=x">Result A</a>
  </h2>
  <a class="result__snippet" href="x">Snippet about A.</a>
</div>
<div class="result results_links">
  <h2 class="result__title">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fb">Result B</a>
  </h2>
  <a class="result__snippet" href="x">Snippet about B.</a>
</div>
"""


def test_duckduckgo_parses_and_unwraps_urls():
    client = _client(lambda req: httpx.Response(200, text=DDG_HTML))
    results = DuckDuckGoSearch(client=client).search("anything", max_results=5)
    assert results[0] == SearchResult(title="Result A", url="https://example.com/a", snippet="Snippet about A.")
    assert results[1].url == "https://example.com/b"


def test_duckduckgo_respects_max_results():
    client = _client(lambda req: httpx.Response(200, text=DDG_HTML))
    assert len(DuckDuckGoSearch(client=client).search("x", max_results=1)) == 1


def test_brave_parses_json():
    payload = {"web": {"results": [
        {"title": "B1", "url": "https://b1", "description": "desc1"},
        {"title": "B2", "url": "https://b2", "description": "desc2"},
    ]}}
    client = _client(lambda req: httpx.Response(200, json=payload))
    results = BraveSearch("key", client=client).search("q", max_results=5)
    assert results[0] == SearchResult(title="B1", url="https://b1", snippet="desc1")


def test_brave_without_key_errors():
    with pytest.raises(ToolError):
        BraveSearch(None).search("q")


def test_tavily_parses_json():
    payload = {"results": [{"title": "T1", "url": "https://t1", "content": "body1"}]}
    client = _client(lambda req: httpx.Response(200, json=payload))
    results = TavilySearch("key", client=client).search("q", max_results=5)
    assert results[0] == SearchResult(title="T1", url="https://t1", snippet="body1")


def test_build_search_provider_by_config():
    assert isinstance(build_search_provider(SearchConfig(provider="duckduckgo")), DuckDuckGoSearch)
    assert isinstance(build_search_provider(SearchConfig(provider="brave")), BraveSearch)
    assert isinstance(build_search_provider(SearchConfig(provider="tavily")), TavilySearch)


def test_web_search_formats_results():
    client = _client(lambda req: httpx.Response(200, text=DDG_HTML))
    out = web_search("q", provider=DuckDuckGoSearch(client=client), max_results=5)
    assert "Result A" in out and "https://example.com/a" in out and "Snippet about A." in out


def test_web_search_no_provider_raises():
    with pytest.raises(ToolError):
        web_search("q", provider=None)


def test_web_search_empty_results_message():
    client = _client(lambda req: httpx.Response(200, text="<html><body>nothing</body></html>"))
    out = web_search("q", provider=DuckDuckGoSearch(client=client))
    assert "No results" in out


@pytest.mark.integration
def test_web_fetch_reads_a_real_page():
    """Canary: web_fetch reads a live page. Run: .venv/bin/python -m pytest -m integration"""
    out = web_fetch("https://example.com", timeout=20)
    assert "Example Domain" in out


@pytest.mark.integration
def test_duckduckgo_search_returns_live_results():
    """Canary: the DDG HTML-scrape contract still parses. DDG markup can drift;
    this catches it. Best-effort — DDG may rate-limit. Run with -m integration."""
    results = DuckDuckGoSearch().search("python programming language", max_results=3)
    assert results, "expected at least one DuckDuckGo result"
    assert results[0].url.startswith("http")
    assert results[0].title
