import os
import socket
import subprocess
import sys
import textwrap
import time

import httpx
import pytest

pytest.importorskip("mcp")  # the MCP SDK is an optional extra (heya-agent[mcp])

from heya.config import MCPServerConfig
from heya.mcp_runtime import MCPRuntime

# A minimal real MCP server using the SDK's FastMCP, run as a child process.
_SERVER = textwrap.dedent('''
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("canary")

    @mcp.tool()
    def echo(text: str) -> str:
        "Echo the text back."
        return f"echo: {text}"

    @mcp.resource("file:///canary.txt")
    def canary_doc() -> str:
        return "canary resource body"

    @mcp.prompt()
    def greet(name: str) -> str:
        "A greeting prompt."
        return f"Say hello to {name}"

    if __name__ == "__main__":
        mcp.run()
''')


@pytest.mark.integration
def test_real_stdio_bridge_end_to_end(tmp_path):
    server_file = tmp_path / "canary_server.py"
    server_file.write_text(_SERVER)
    runtime = MCPRuntime([MCPServerConfig(
        name="canary", command=sys.executable, args=(str(server_file),),
    )], connect_timeout=20.0)
    runtime.connect_all()
    try:
        names = [s["name"] for _, s in runtime.list_tools()]
        assert "echo" in names
        out = runtime.call_tool("canary", "echo", {"text": "hi"})
        assert "echo: hi" in out
    finally:
        runtime.close()


@pytest.mark.integration
def test_real_resources_and_prompts(tmp_path):
    server_file = tmp_path / "canary_server.py"
    server_file.write_text(_SERVER)
    runtime = MCPRuntime([MCPServerConfig(
        name="canary", command=sys.executable, args=(str(server_file),),
    )], connect_timeout=20.0)
    runtime.connect_all()
    try:
        assert runtime.has_resources() is True
        assert runtime.has_prompts() is True
        uris = [r["uri"] for _, r in runtime.list_resources()]
        assert "file:///canary.txt" in uris
        assert "canary resource body" in runtime.read_resource("canary", "file:///canary.txt")
        names = [p["name"] for _, p in runtime.list_prompts()]
        assert "greet" in names
        assert "hello" in runtime.get_prompt("canary", "greet", {"name": "Ada"}).lower()
    finally:
        runtime.close()


# ---------------------------------------------------------------------------
# HTTP transport canary
# ---------------------------------------------------------------------------

_HTTP_SERVER = textwrap.dedent('''
    import sys
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("http-canary", host="127.0.0.1", port=int(sys.argv[1]))

    @mcp.tool()
    def echo(text: str) -> str:
        "Echo the text back."
        return f"echo: {text}"

    if __name__ == "__main__":
        mcp.run(transport="streamable-http")
''')


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _spawn_http_server(tmp_path, body, port, env=None):
    f = tmp_path / "http_server.py"
    f.write_text(body)
    proc = subprocess.Popen([sys.executable, str(f), str(port)], env=env)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    return proc


@pytest.mark.integration
def test_real_http_transport_round_trip(tmp_path):
    port = _free_port()
    proc = _spawn_http_server(tmp_path, _HTTP_SERVER, port)
    try:
        rt = MCPRuntime([MCPServerConfig(
            name="hc", transport="http", url=f"http://127.0.0.1:{port}/mcp",
        )], connect_timeout=20.0)
        rt.connect_all()
        try:
            assert "echo" in [s["name"] for _, s in rt.list_tools()]
            assert "echo: hi" in rt.call_tool("hc", "echo", {"text": "hi"})
        finally:
            rt.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# ---------------------------------------------------------------------------
# Bearer-auth canary
# ---------------------------------------------------------------------------

# Uses BaseHTTPMiddleware (Starlette) rather than @app.middleware("http")
# (which is FastAPI-specific) — streamable_http_app() returns a Starlette app.
_AUTH_HTTP_SERVER = textwrap.dedent('''
    import sys
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("auth-canary", host="127.0.0.1", port=int(sys.argv[1]))

    @mcp.tool()
    def echo(text: str) -> str:
        "Echo."
        return f"echo: {text}"

    app = mcp.streamable_http_app()
    REQUIRED = "Bearer canary-secret"

    class _AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.headers.get("authorization") != REQUIRED:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    app.add_middleware(_AuthMiddleware)

    if __name__ == "__main__":
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="error")
''')


@pytest.mark.integration
def test_real_http_bearer_auth(tmp_path):
    port = _free_port()
    proc = _spawn_http_server(tmp_path, _AUTH_HTTP_SERVER, port)
    try:
        url = f"http://127.0.0.1:{port}/mcp"

        # Without the token env var set -> ToolError inside _build_headers -> skipped
        os.environ.pop("CANARY_TOKEN", None)
        rt_no = MCPRuntime(
            [MCPServerConfig(name="a", transport="http", url=url, auth_token_env="CANARY_TOKEN")],
            connect_timeout=20.0,
        )
        rt_no.connect_all()
        try:
            assert rt_no.list_tools() == []  # skipped: missing token env var
        finally:
            rt_no.close()

        # With the correct token -> connects and round-trips
        os.environ["CANARY_TOKEN"] = "canary-secret"
        try:
            rt = MCPRuntime(
                [MCPServerConfig(name="a", transport="http", url=url, auth_token_env="CANARY_TOKEN")],
                connect_timeout=20.0,
            )
            rt.connect_all()
            try:
                assert "echo" in [s["name"] for _, s in rt.list_tools()]
                assert "echo: hi" in rt.call_tool("a", "echo", {"text": "hi"})
            finally:
                rt.close()
        finally:
            os.environ.pop("CANARY_TOKEN", None)
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# ---------------------------------------------------------------------------
# Custom-CA canary
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_real_http_custom_ca(tmp_path):
    import trustme

    ca = trustme.CA()
    server_cert = ca.issue_cert("127.0.0.1")
    ca_file = tmp_path / "ca.pem"
    ca.cert_pem.write_to_path(str(ca_file))
    cert_file = tmp_path / "server.pem"
    key_file = tmp_path / "server.key"
    server_cert.cert_chain_pems[0].write_to_path(str(cert_file))
    server_cert.private_key_pem.write_to_path(str(key_file))

    port = _free_port()
    body = textwrap.dedent(f'''
        import sys, uvicorn
        from mcp.server.fastmcp import FastMCP
        mcp = FastMCP("ca-canary", host="127.0.0.1", port={port})

        @mcp.tool()
        def echo(text: str) -> str:
            "Echo."
            return f"echo: {{text}}"

        if __name__ == "__main__":
            uvicorn.run(
                mcp.streamable_http_app(),
                host="127.0.0.1",
                port={port},
                ssl_certfile=r"{cert_file}",
                ssl_keyfile=r"{key_file}",
                log_level="error",
            )
    ''')
    f = tmp_path / "tls_server.py"
    f.write_text(body)
    proc = subprocess.Popen([sys.executable, str(f)])
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    try:
        url = f"https://127.0.0.1:{port}/mcp"

        # Default verify -> self-signed cert fails -> server skipped, no tools
        rt_bad = MCPRuntime(
            [MCPServerConfig(name="c", transport="http", url=url)],
            connect_timeout=20.0,
        )
        rt_bad.connect_all()
        try:
            assert rt_bad.list_tools() == []
        finally:
            rt_bad.close()

        # Custom CA -> verifies -> connects and lists tools
        rt = MCPRuntime(
            [MCPServerConfig(name="c", transport="http", url=url, tls_ca_cert=str(ca_file))],
            connect_timeout=20.0,
        )
        rt.connect_all()
        try:
            assert "echo" in [s["name"] for _, s in rt.list_tools()]
        finally:
            rt.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# ---------------------------------------------------------------------------
# CA + mTLS canary: the client cert is folded into the SSLContext (no cert=)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_real_http_ca_and_mtls(tmp_path):
    import trustme

    ca = trustme.CA()
    server_cert = ca.issue_cert("127.0.0.1")
    client_cert = ca.issue_cert("client@canary")

    ca_file = tmp_path / "ca.pem"
    ca.cert_pem.write_to_path(str(ca_file))
    srv_cert = tmp_path / "server.pem"
    srv_key = tmp_path / "server.key"
    server_cert.cert_chain_pems[0].write_to_path(str(srv_cert))
    server_cert.private_key_pem.write_to_path(str(srv_key))
    cli_cert = tmp_path / "client.pem"
    cli_key = tmp_path / "client.key"
    client_cert.cert_chain_pems[0].write_to_path(str(cli_cert))
    client_cert.private_key_pem.write_to_path(str(cli_key))

    port = _free_port()
    body = textwrap.dedent(f'''
        import ssl, uvicorn
        from mcp.server.fastmcp import FastMCP
        mcp = FastMCP("mtls-canary", host="127.0.0.1", port={port})

        @mcp.tool()
        def echo(text: str) -> str:
            "Echo."
            return f"echo: {{text}}"

        if __name__ == "__main__":
            uvicorn.run(
                mcp.streamable_http_app(),
                host="127.0.0.1",
                port={port},
                ssl_certfile=r"{srv_cert}",
                ssl_keyfile=r"{srv_key}",
                ssl_ca_certs=r"{ca_file}",
                ssl_cert_reqs=ssl.CERT_REQUIRED,
                log_level="error",
            )
    ''')
    f = tmp_path / "mtls_server.py"
    f.write_text(body)
    proc = subprocess.Popen([sys.executable, str(f)])
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    try:
        url = f"https://127.0.0.1:{port}/mcp"

        # CA only (no client cert): server REQUIRES a client cert -> handshake fails -> skipped
        rt_no_client = MCPRuntime(
            [MCPServerConfig(name="m", transport="http", url=url, tls_ca_cert=str(ca_file))],
            connect_timeout=20.0,
        )
        rt_no_client.connect_all()
        try:
            assert rt_no_client.list_tools() == []
        finally:
            rt_no_client.close()

        # CA + client cert -> mTLS handshake succeeds -> connects and round-trips
        rt = MCPRuntime(
            [MCPServerConfig(
                name="m", transport="http", url=url,
                tls_ca_cert=str(ca_file),
                tls_client_cert=str(cli_cert), tls_client_key=str(cli_key),
            )],
            connect_timeout=20.0,
        )
        rt.connect_all()
        try:
            assert "echo" in [s["name"] for _, s in rt.list_tools()]
            assert "echo: hi" in rt.call_tool("m", "echo", {"text": "hi"})
        finally:
            rt.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# ---------------------------------------------------------------------------
# OAuth end-to-end canary
# ---------------------------------------------------------------------------

# Combined OAuth AS + FastMCP resource server.
#
# Endpoints served:
#   /.well-known/oauth-protected-resource      RFC 9728 PRM metadata
#   /.well-known/oauth-protected-resource/mcp  (path-based fallback)
#   /.well-known/oauth-authorization-server    RFC 8414 OASM metadata
#   POST /register                              RFC 7591 DCR
#   GET  /authorize                             authorization endpoint (302 to loopback)
#   POST /token                                 token endpoint
#   /mcp                                        FastMCP streamable-http (bearer-guarded)
#
# The Bearer guard returns 401 with WWW-Authenticate: Bearer on the /mcp
# route for any request that does not carry the valid access token; this
# triggers the SDK's OAuthClientProvider flow.
_OAUTH_SERVER = textwrap.dedent('''\
    import sys
    import secrets
    import uvicorn
    from urllib.parse import urlencode
    from starlette.routing import Route
    from starlette.requests import Request
    from starlette.responses import JSONResponse, RedirectResponse
    from starlette.middleware.base import BaseHTTPMiddleware
    from mcp.server.fastmcp import FastMCP

    PORT = int(sys.argv[1])
    BASE = f"http://127.0.0.1:{PORT}"
    ACCESS_TOKEN = "canary-oauth-" + secrets.token_hex(8)

    mcp = FastMCP("oauth-canary", host="127.0.0.1", port=PORT)

    @mcp.tool()
    def echo(text: str) -> str:
        "Echo the text back."
        return f"echo: {text}"

    mcp_app = mcp.streamable_http_app()

    _clients: dict = {}
    _codes: dict = {}

    # Paths that bypass the bearer guard (OAuth negotiation traffic)
    _OPEN_PATHS = frozenset({
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/mcp",
        "/.well-known/oauth-authorization-server",
        "/register",
        "/authorize",
        "/token",
    })

    class _BearerGuard(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.url.path in _OPEN_PATHS:
                return await call_next(request)
            if request.headers.get("authorization") == f"Bearer {ACCESS_TOKEN}":
                return await call_next(request)
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

    mcp_app.add_middleware(_BearerGuard)

    async def _prm(request: Request):
        return JSONResponse({
            "resource": f"{BASE}/mcp",
            "authorization_servers": [BASE],
        })

    async def _oasm(request: Request):
        return JSONResponse({
            "issuer": BASE,
            "authorization_endpoint": f"{BASE}/authorize",
            "token_endpoint": f"{BASE}/token",
            "registration_endpoint": f"{BASE}/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
        })

    async def _register(request: Request):
        body = await request.json()
        client_id = "client-" + secrets.token_hex(8)
        info = {
            "client_id": client_id,
            "redirect_uris": body.get("redirect_uris", []),
            "token_endpoint_auth_method": "none",
            "grant_types": body.get("grant_types", ["authorization_code"]),
            "response_types": body.get("response_types", ["code"]),
        }
        _clients[client_id] = info
        return JSONResponse(info, status_code=201)

    async def _authorize(request: Request):
        params = dict(request.query_params)
        redirect_uri = params.get("redirect_uri", "")
        state = params.get("state")
        code = "code-" + secrets.token_hex(8)
        _codes[code] = {"client_id": params.get("client_id"), "redirect_uri": redirect_uri}
        qs_parts = {"code": code}
        if state:
            qs_parts["state"] = state
        return RedirectResponse(f"{redirect_uri}?{urlencode(qs_parts)}", status_code=302)

    async def _token(request: Request):
        form = await request.form()
        grant_type = form.get("grant_type")
        code = form.get("code")
        if grant_type == "authorization_code" and code and code in _codes:
            del _codes[code]
            return JSONResponse({
                "access_token": ACCESS_TOKEN,
                "token_type": "Bearer",
                "expires_in": 3600,
            })
        return JSONResponse({"error": "invalid_grant"}, status_code=400)

    mcp_app.router.routes.extend([
        Route("/.well-known/oauth-protected-resource", _prm),
        Route("/.well-known/oauth-protected-resource/mcp", _prm),
        Route("/.well-known/oauth-authorization-server", _oasm),
        Route("/register", _register, methods=["POST"]),
        Route("/authorize", _authorize),
        Route("/token", _token, methods=["POST"]),
    ])

    if __name__ == "__main__":
        uvicorn.run(mcp_app, host="127.0.0.1", port=PORT, log_level="error")
''')


# ---------------------------------------------------------------------------
# Callbacks canary: sampling + elicitation + logging, driven via MCPRuntime
# ---------------------------------------------------------------------------

# ctx.elicit() in mcp 1.28.0 requires a Pydantic model class (not a raw dict schema).
# The elicitation result for an accepted call is AcceptedElicitation whose .data
# is an instance of that model.  ctx.session.create_message() is on ServerSession.
# ctx.log(level, message) sends a log notification to the client.
_CALLBACK_SERVER = textwrap.dedent('''\
    import sys
    from pydantic import BaseModel
    from mcp.server.fastmcp import FastMCP, Context
    from mcp.types import SamplingMessage, TextContent

    mcp = FastMCP("cb")

    class _AnswerSchema(BaseModel):
        answer: str

    @mcp.tool()
    async def do_things(ctx: Context) -> str:
        # logging — ctx.log(level, message) in mcp 1.28.0
        await ctx.log(level="info", message="cb tool ran")

        # sampling — ctx.session is the underlying ServerSession
        try:
            res = await ctx.session.create_message(
                messages=[SamplingMessage(role="user", content=TextContent(type="text", text="ping"))],
                max_tokens=50,
            )
            sampled = res.content.text
        except Exception as exc:
            sampled = f"sampling-error: {exc}"

        # elicitation — ctx.elicit takes a Pydantic model class in mcp 1.28.0
        try:
            elic = await ctx.elicit(message="answer?", schema=_AnswerSchema)
            # elic is AcceptedElicitation | DeclinedElicitation | CancelledElicitation
            # AcceptedElicitation has .data which is the _AnswerSchema instance
            data = getattr(elic, "data", None)
            answer = data.answer if data is not None else str(elic.action)
        except Exception as exc:
            answer = f"elicit-error: {exc}"

        return f"sampled={sampled} answer={answer}"

    if __name__ == "__main__":
        mcp.run()
''')


@pytest.mark.integration
def test_real_callbacks_end_to_end(tmp_path):
    server_file = tmp_path / "cb_server.py"
    server_file.write_text(_CALLBACK_SERVER)

    class _Profile:
        model = "fake"

    class _LLM:
        profile = _Profile()

        def chat(self, messages, tools=None):
            class R:
                content = "SAMPLED:" + messages[-1]["content"]
            return R()

    class _Prompter:
        def form(self, server, message, schema):
            return {"answer": "42"}

        def url(self, server, message, url):
            return True

    logs = []
    rt = MCPRuntime(
        [MCPServerConfig(name="cb", command=sys.executable, args=(str(server_file),))],
        connect_timeout=20.0,
        llm_client=_LLM(),
        sampling_approver=lambda server, preview: True,
        elicit_prompter=_Prompter(),
        log_sink=logs.append,
    )
    rt.connect_all()
    try:
        out = rt.call_tool("cb", "do_things", {})
        assert "SAMPLED:" in out, f"expected 'SAMPLED:' in output, got: {out!r}"
        assert "42" in out, f"expected '42' in output, got: {out!r}"
        assert any("cb" in line for line in logs), f"expected a log line from 'cb', got: {logs!r}"
    finally:
        rt.close()


@pytest.mark.integration
def test_real_sampling_declined(tmp_path):
    server_file = tmp_path / "cb_server.py"
    server_file.write_text(_CALLBACK_SERVER)

    class _Profile:
        model = "fake"

    class _LLM:
        profile = _Profile()

        def chat(self, messages, tools=None):
            class R:
                content = "should-not-be-used"
            return R()

    rt = MCPRuntime(
        [MCPServerConfig(name="cb", command=sys.executable, args=(str(server_file),))],
        connect_timeout=20.0,
        llm_client=_LLM(),
        sampling_approver=lambda server, preview: False,  # decline
        elicit_prompter=type(
            "P", (),
            {"form": lambda *a: {"answer": "x"}, "url": lambda *a: True},
        )(),
        log_sink=lambda l: None,
    )
    rt.connect_all()
    try:
        out = rt.call_tool("cb", "do_things", {})
        assert "declined" in out.lower() or "error" in out.lower(), (
            f"expected sampling decline/error reflected in output, got: {out!r}"
        )
    finally:
        rt.close()


def _spawn_oauth_server(tmp_path, port):
    f = tmp_path / "oauth_server.py"
    f.write_text(_OAUTH_SERVER)
    proc = subprocess.Popen([sys.executable, str(f), str(port)])
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    return proc


@pytest.mark.integration
def test_real_oauth_end_to_end(tmp_path, monkeypatch):
    """Prove the full OAuth flow: discover → DCR → PKCE authorize → token → connect."""
    port = _free_port()
    proc = _spawn_oauth_server(tmp_path, port)
    try:
        import heya.mcp_oauth as oauth_mod

        browser_calls = []

        async def _do_redirect(url: str) -> None:
            async with httpx.AsyncClient(follow_redirects=True) as c:
                await c.get(url)

        async def auto_browser(url: str) -> None:
            # Schedule the redirect follow-through as a background task so
            # the SDK can call wait_for_code() and suspend on its future
            # before the loopback callback arrives.  If we await the GET
            # directly here the loopback fires before the future exists and
            # the code is lost.
            browser_calls.append(url)
            import asyncio as _asyncio
            _asyncio.ensure_future(_do_redirect(url))

        monkeypatch.setattr(oauth_mod, "open_browser_redirect", auto_browser)

        rt = MCPRuntime(
            [MCPServerConfig(
                name="o",
                transport="http",
                url=f"http://127.0.0.1:{port}/mcp",
                auth="oauth",
                oauth_token_store="memory",
            )],
            oauth_prompt=lambda name: True,
            connect_timeout=60.0,
        )
        rt.connect_all()
        try:
            # First connect: full OAuth round-trip runs, browser invoked once.
            assert "echo" in [s["name"] for _, s in rt.list_tools()]
            assert "echo: hi" in rt.call_tool("o", "echo", {"text": "hi"})
            assert len(browser_calls) == 1, (
                f"first connect should authorize once; got {len(browser_calls)}"
            )

            # Token-reuse proof: a SECOND connect on the same runtime reuses the
            # cached per-server InMemoryTokenStorage. The provider reads the stored
            # token, the first /mcp request carries it, no 401 is returned, and the
            # authorize/browser step is skipped entirely. If the token were not
            # cached, run 2 would hit 401 -> discovery -> /authorize -> a second
            # browser call, and this assertion would fail with len == 2.
            rt.connect_all()
            assert "echo" in [s["name"] for _, s in rt.list_tools()]
            assert "echo: hi" in rt.call_tool("o", "echo", {"text": "hi"})
            assert len(browser_calls) == 1, (
                "second connect must reuse the cached token and skip authorize; "
                f"browser was called {len(browser_calls)} times"
            )
        finally:
            rt.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
