"""Sub-agent building blocks: roles, child-prompt composition, labeled output.

Pure helpers with no dependency on Agent (avoids an import cycle). Agent imports
this module; this module never imports Agent.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

SUBAGENT_FRAMING = (
    "You are a focused sub-agent spawned to complete one specific task. Do exactly "
    "that task using your tools, then reply with a concise report of what you found "
    "or did. You do not see the parent conversation, so rely only on the task "
    "description and what your tools return."
)


@dataclass(frozen=True)
class Role:
    name: str
    system_addendum: str
    tools: frozenset[str] | None = None  # None = inherit full toolbox


_RESEARCHER_TOOLS = frozenset({
    "read_file", "read_guidance", "web_search", "web_fetch", "read_log",
    "mcp_list_resources", "mcp_read_resource", "mcp_list_prompts", "mcp_get_prompt",
})
_REVIEWER_TOOLS = frozenset({"read_file", "read_guidance", "read_log"})

ROLES: dict[str, Role] = {
    "researcher": Role(
        "researcher",
        "Investigate and report findings; do not modify anything.",
        _RESEARCHER_TOOLS,
    ),
    "reviewer": Role(
        "reviewer",
        "Critically review the target for correctness and quality; report issues "
        "with file:line references; do not change code.",
        _REVIEWER_TOOLS,
    ),
}


def resolve_role(name: str | None) -> Role | None:
    """Return the Role for a name, or None (unknown name or None)."""
    if not name:
        return None
    return ROLES.get(name)


def build_child_system_prompt(
    base: str, role: Role | None, instructions: str | None
) -> str:
    """Compose a child's system prompt: base + framing + role addendum + extras."""
    parts = [base, SUBAGENT_FRAMING]
    if role is not None:
        parts.append(role.system_addendum)
    if instructions:
        parts.append(instructions)
    return "\n\n".join(parts)
