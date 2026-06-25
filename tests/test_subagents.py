import pytest
from heya.subagents import (
    Role, ROLES, resolve_role, build_child_system_prompt, SUBAGENT_FRAMING,
)


def test_resolve_known_role_returns_role():
    role = resolve_role("researcher")
    assert isinstance(role, Role)
    assert role.name == "researcher"


def test_resolve_unknown_role_returns_none():
    assert resolve_role("nope") is None


def test_resolve_none_returns_none():
    assert resolve_role(None) is None


def test_roles_are_read_only_subsets():
    # The two starter roles must not be able to mutate.
    for key in ("researcher", "reviewer"):
        tools = ROLES[key].tools
        assert tools is not None
        assert "write_file" not in tools
        assert "run_command" not in tools
        assert "run_wp_cli" not in tools


def test_build_prompt_base_only():
    out = build_child_system_prompt("BASE", None, None)
    assert "BASE" in out
    assert SUBAGENT_FRAMING in out


def test_build_prompt_with_role_includes_addendum():
    out = build_child_system_prompt("BASE", ROLES["reviewer"], None)
    assert "BASE" in out
    assert SUBAGENT_FRAMING in out
    assert ROLES["reviewer"].system_addendum in out


def test_build_prompt_with_instructions_includes_them():
    out = build_child_system_prompt("BASE", None, "FOCUS HERE")
    assert "FOCUS HERE" in out


def test_build_prompt_with_role_and_instructions_includes_both():
    out = build_child_system_prompt("BASE", ROLES["researcher"], "EXTRA")
    assert ROLES["researcher"].system_addendum in out
    assert "EXTRA" in out
