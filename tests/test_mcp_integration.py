import os
import socket
import subprocess
import sys
import textwrap
import time

import pytest

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
