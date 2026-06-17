import httpx
import pytest

from heya.tools_web import web_fetch
from heya.tools_files import ToolError

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
