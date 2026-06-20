"""Approval gate for write/command tools.

Reads run automatically; write_file and run_command are gated. The prompt is an
injectable callback returning "yes" | "no" | "always", so the loop is testable
without stdin and the CLI supplies a real prompt.
"""
from __future__ import annotations

from collections.abc import Callable

GATED_TOOLS = frozenset({
    "write_file", "run_command", "browser_click", "browser_type",
    "run_wp_cli", "wp_playground", "kill_command",
})

Approver = Callable[[str, str], str]


def prompt_stdin(name: str, detail: str) -> str:
    """Default approver: ask on the terminal. Returns yes | no | always."""
    answer = input(f"Allow {detail}? [y]es / [n]o / [a]lways: ").strip().lower()
    if answer in ("a", "always"):
        return "always"
    if answer in ("y", "yes"):
        return "yes"
    return "no"


class ApprovalPolicy:
    def __init__(
        self,
        *,
        auto_approve: bool = False,
        approver: Approver = prompt_stdin,
        allow: tuple[str, ...] = (),
    ) -> None:
        self.auto_approve = auto_approve
        self._approver = approver
        self._allow = tuple(allow)
        self._always: set[str] = set()

    @staticmethod
    def _command_of(detail: str) -> str:
        """The command portion of a describe_call string ('name → cmd' → 'cmd')."""
        return detail.split("→", 1)[1].strip() if "→" in detail else detail.strip()

    def check(self, name: str, detail: str) -> bool:
        """Return True if the tool may run."""
        is_mcp = name.startswith("mcp__")
        if name not in GATED_TOOLS and not is_mcp:
            return True
        if self.auto_approve or name in self._always:
            return True
        command = self._command_of(detail)
        candidates = (command, name) if is_mcp else (command,)
        if any(c.startswith(prefix) for c in candidates for prefix in self._allow):
            return True
        decision = self._approver(name, detail)
        if decision == "always":
            self._always.add(name)
            return True
        return decision == "yes"
