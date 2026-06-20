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
