"""Discover Claude sub-agent definitions (agents/*.md) as Heya Roles.

A Claude agent .md has frontmatter (name, description, tools, ...) and a body
(the system prompt). That maps directly onto heya.subagents.Role. 13d reads
name/description/tools and the body; model/effort/etc. are parsed-and-ignored.
Discovery never raises (missing dirs, unreadable/malformed files skipped)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .skills import _split_tools, _strip_frontmatter, translate_allowed_tools
from .subagents import Role
from .tools_guidance import _frontmatter

_MAX_AGENTS_LISTED = 50


def discover_agent_roles(dirs: Sequence[Path]) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for entry in sorted(d.iterdir()):
            if not entry.is_file() or entry.suffix.lower() != ".md":
                continue
            try:
                text = entry.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fm = _frontmatter(text)
            name = fm.get("name", "") or entry.stem
            description = fm.get("description", "")
            raw_tools = fm.get("tools", "") or fm.get("allowed-tools", "")
            tools = translate_allowed_tools(_split_tools(raw_tools))
            # wildcard '*' means inherit full toolbox (None), not a literal tool
            if tools == ("*",) or "*" in tools:
                tools = ()
            body = _strip_frontmatter(text).strip()
            addendum = body or description or f"You are the {name} sub-agent."
            roles[name] = Role(
                name=name, system_addendum=addendum,
                tools=frozenset(tools) if tools else None,
            )
    return roles


def agent_roles_note(roles) -> str:
    """A short listing of discovered agents for the system prompt."""
    if not roles:
        return ""
    names = sorted(roles)
    lines = ["Sub-agents available for spawn_agent(role=...):"]
    for name in names[:_MAX_AGENTS_LISTED]:
        first = (roles[name].system_addendum or "").strip().splitlines()
        summary = (first[0] if first else "")[:120]
        lines.append(f"- {name}: {summary}")
    extra = len(names) - _MAX_AGENTS_LISTED
    if extra > 0:
        lines.append(f"- (+{extra} more agents)")
    return "\n".join(lines)
