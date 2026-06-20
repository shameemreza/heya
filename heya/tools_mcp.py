"""The seam between dynamic MCP tools and Heya's static tool layer.

MCP tools are discovered from servers at runtime; Heya's model-facing tools are
named, namespaced functions. This module names them (`mcp__<server>__<tool>`,
sanitized to valid identifier chars), builds the reverse map dispatch uses to
recover the original (server, tool), and turns a runtime snapshot into
OpenAI-style tool schemas.
"""
from __future__ import annotations

MCP_PREFIX = "mcp__"
_MAX_DESC = 1024  # cap a verbose server's tool description so it can't blow the prompt


def _safe(part: str) -> str:
    return "".join(ch if (ch.isascii() and (ch.isalnum() or ch == "_")) else "_" for ch in part)


def mcp_tool_name(server: str, tool: str) -> str:
    return f"{MCP_PREFIX}{_safe(server)}__{_safe(tool)}"


def build_reverse_map(snapshot: list[tuple[str, dict]]) -> dict[str, tuple[str, str]]:
    """Map each surfaced tool's namespaced name back to its original (server, tool)."""
    reverse: dict[str, tuple[str, str]] = {}
    for server, schema in snapshot:
        tool = schema["name"]
        reverse[mcp_tool_name(server, tool)] = (server, tool)
    return reverse


def parse_mcp_name(name: str, reverse: dict[str, tuple[str, str]]) -> tuple[str, str] | None:
    return reverse.get(name)
