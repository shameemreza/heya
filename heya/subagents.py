"""Sub-agent building blocks: roles, child-prompt composition, labeled output.

Pure helpers with no dependency on Agent (avoids an import cycle). Agent imports
this module; this module never imports Agent.
"""
from __future__ import annotations

import threading
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


# the read-only, thread-safe tool surface: safe to run concurrently and never
# mutates. Used both for the `researcher` role and for parallel sub-agents.
PARALLEL_SAFE_TOOLS = frozenset({
    "read_file", "read_guidance", "web_search", "web_fetch", "read_log", "search_files",
    "mcp_list_resources", "mcp_read_resource", "mcp_list_prompts", "mcp_get_prompt",
})
_RESEARCHER_TOOLS = PARALLEL_SAFE_TOOLS
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

BACKGROUND_TOOLS = PARALLEL_SAFE_TOOLS | frozenset({
    "write_file", "run_command", "check_command", "kill_command", "run_wp_cli",
})

ROLES["background"] = Role(
    "background",
    "You run as a background agent on an independent task. You may read, and "
    "within your granted folder you may write files and run commands. Do the "
    "task end to end, then reply with a short report of what you produced.",
    BACKGROUND_TOOLS,
)


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


def parallel_label(role_name: str | None, index: int) -> str:
    """A distinguishable label for one parallel child (same-role children differ)."""
    return f"{role_name or 'agent'}#{index}"


MAX_REPORT_CHARS = 6000

_STATUS_PREFIX = {"ok": "", "failed": "(failed) ", "timed-out": "(timed out) "}


def format_parallel_report(label: str, task: str, body: str, *, status: str = "ok") -> str:
    """Format one parallel child's report as a section, truncating the body with an
    explicit marker (never a silent cut) so the parent's synthesis sees the loss."""
    text = body or ""
    if len(text) > MAX_REPORT_CHARS:
        text = text[:MAX_REPORT_CHARS] + "\n…[report truncated]"
    return f"## [{label}] {_STATUS_PREFIX.get(status, '')}{task}\n{text}"


class LabeledStream:
    """Wrap a text sink so each completed line is prefixed with [label].

    Buffers partial lines so a label is only ever added at a line start, never
    mid-token (chat output arrives in arbitrary chunks). close() flushes a final
    unterminated line.
    """

    def __init__(self, sink: Callable[[str], None], label: str) -> None:
        self._sink = sink
        self._prefix = f"[{label}] "
        self._buf = ""

    def write(self, text: str) -> None:
        if not text:
            return
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._sink(self._prefix + line + "\n")

    def close(self) -> None:
        if self._buf:
            self._sink(self._prefix + self._buf)
            self._buf = ""


class LockedSink:
    """Serialize writes to a text sink so concurrent sub-agents never interleave a
    single write. Callers (LabeledStream) already emit whole lines, so locking each
    write makes each labeled line atomic on the shared terminal."""

    def __init__(self, sink: Callable[[str], None]) -> None:
        self._sink = sink
        self._lock = threading.Lock()

    def write(self, text: str) -> None:
        with self._lock:
            self._sink(text)
