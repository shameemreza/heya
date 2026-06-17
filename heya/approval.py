"""Approval gate for write/command tools.

Reads run automatically; write_file and run_command are gated. The prompt is an
injectable callback returning "yes" | "no" | "always", so the loop is testable
without stdin and the CLI supplies a real prompt.
"""
from __future__ import annotations

from collections.abc import Callable

GATED_TOOLS = frozenset({"write_file", "run_command"})

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
    def __init__(self, *, auto_approve: bool = False, approver: Approver = prompt_stdin) -> None:
        self.auto_approve = auto_approve
        self._approver = approver
        self._always: set[str] = set()

    def check(self, name: str, detail: str) -> bool:
        """Return True if the tool may run."""
        if name not in GATED_TOOLS:
            return True
        if self.auto_approve or name in self._always:
            return True
        decision = self._approver(name, detail)
        if decision == "always":
            self._always.add(name)
            return True
        return decision == "yes"
