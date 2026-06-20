from heya.tools_mcp import (
    MCP_PREFIX, mcp_tool_name, parse_mcp_name, build_reverse_map,
)


def test_mcp_tool_name_basic():
    assert mcp_tool_name("linear", "create_issue") == "mcp__linear__create_issue"


def test_mcp_tool_name_sanitizes_unsafe_chars():
    # hyphens, dots, slashes are not valid function-name chars
    assert mcp_tool_name("context-a8c", "load.provider") == "mcp__context_a8c__load_provider"


def test_build_reverse_map_round_trips_original_names():
    snapshot = [
        ("context-a8c", {"name": "load.provider"}),
        ("context-a8c", {"name": "execute-tool"}),
    ]
    reverse = build_reverse_map(snapshot)
    assert parse_mcp_name("mcp__context_a8c__load_provider", reverse) == ("context-a8c", "load.provider")
    assert parse_mcp_name("mcp__context_a8c__execute_tool", reverse) == ("context-a8c", "execute-tool")


def test_parse_mcp_name_unknown_returns_none():
    assert parse_mcp_name("mcp__nope__nope", {}) is None
    assert parse_mcp_name("read_file", {}) is None


def test_mcp_prefix_value():
    assert MCP_PREFIX == "mcp__"
