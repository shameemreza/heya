import sys
import textwrap

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
