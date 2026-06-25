"""Approval gate for write/command tools.

Reads run automatically; write_file and run_command are gated. The prompt is an
injectable callback returning "yes" | "no" | "always", so the loop is testable
without stdin and the CLI supplies a real prompt.
"""
from __future__ import annotations

import threading
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
        self._lock = threading.Lock()

    @staticmethod
    def _command_of(detail: str) -> str:
        """The command portion of a describe_call string ('name → cmd' → 'cmd')."""
        return detail.split("→", 1)[1].strip() if "→" in detail else detail.strip()

    def check(self, name: str, detail: str, label: str = "") -> bool:
        """Return True if the tool may run. `label` names the agent asking."""
        is_mcp = name.startswith("mcp__")
        if name not in GATED_TOOLS and not is_mcp:
            return True
        if self.auto_approve or name in self._always:
            return True
        command = self._command_of(detail)
        candidates = (command, name) if is_mcp else (command,)
        if any(c.startswith(prefix) for c in candidates for prefix in self._allow if prefix):
            return True
        display = f"[{label}] {detail}" if label else detail
        with self._lock:
            if name in self._always:  # double-checked: another thread may have set it
                return True
            decision = self._approver(name, display)
            if decision == "always":
                self._always.add(name)
                return True
            return decision == "yes"

    def check_sampling(self, server: str, preview: str) -> bool:
        """Gate a server-initiated sampling request, reusing the allow list."""
        name = f"mcp_sample:{server}"
        if self.auto_approve or name in self._always:
            return True
        if any(name.startswith(prefix) for prefix in self._allow if prefix):
            return True
        with self._lock:
            if name in self._always:
                return True
            decision = self._approver(name, f"sampling for {server}: {preview}")
            if decision == "always":
                self._always.add(name)
                return True
            return decision == "yes"
