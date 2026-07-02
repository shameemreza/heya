"""Approval gate for write/command tools.

Reads run automatically; write_file and run_command are gated. The prompt is an
injectable callback returning "yes" | "no" | "always", so the loop is testable
without stdin and the CLI supplies a real prompt.
"""
from __future__ import annotations

import difflib
import shlex
import threading
from collections.abc import Callable
from pathlib import Path

_SHELL_METACHARS = (";", "&&", "||", "|", "`", "$(", ">", "<", "&", "\n")
_COMMAND_TOOLS = frozenset({"run_command", "run_wp_cli"})


def _has_metachars(cmd: str) -> bool:
    return any(m in cmd for m in _SHELL_METACHARS)


def _argv_prefix_match(command: str, prefix: str) -> bool:
    """Return True iff *command* has no shell metacharacters and its argv tokens
    start with *prefix*'s tokens."""
    if _has_metachars(command):
        return False
    try:
        cmd_tokens = shlex.split(command)
        pre_tokens = shlex.split(prefix)
    except ValueError:
        return False
    return bool(pre_tokens) and cmd_tokens[: len(pre_tokens)] == pre_tokens


GATED_TOOLS = frozenset({
    "write_file", "run_command", "browser_click", "browser_type",
    "run_wp_cli", "wp_playground", "kill_command",
    "wp_run_ability", "wp_rest",
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


def unified_file_diff(path: str | Path, new_content: str) -> str:
    """Return a unified diff of *path* on-disk vs *new_content*, or empty string."""
    p = Path(path)
    try:
        old_lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except FileNotFoundError:
        old_lines = []
    new_lines = new_content.splitlines(keepends=True)
    name = str(p)
    lines = list(difflib.unified_diff(old_lines, new_lines, fromfile=name, tofile=name))
    return "".join(lines)


class UiApprover:
    """Approver that renders a colored diff via UI.approval for write_file calls.

    Stores a pending diff (set by the agent before calling approval.check) and
    clears it after each prompt so subsequent non-write approvals get no diff.
    """

    def __init__(self, ui: object) -> None:
        self._ui = ui
        self._pending_diff: str | None = None

    def set_diff(self, diff: str | None) -> None:
        self._pending_diff = diff

    def __call__(self, name: str, detail: str) -> str:
        diff = self._pending_diff
        self._pending_diff = None
        approval_method = getattr(self._ui, "approval", None)
        if callable(approval_method):
            answer = approval_method(detail, diff=diff or None)
            if answer in ("a", "always"):
                return "always"
            if answer in ("y", "yes", "y"):
                return "yes"
            return "no"
        return prompt_stdin(name, detail)


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
        command = self._command_of(detail)
        # Command tools use a per-command key so "always" is scoped to a specific
        # argv, not the tool name. Non-command tools keep tool-level "always".
        always_key = f"{name}:{command}" if name in _COMMAND_TOOLS else name
        if self.auto_approve or always_key in self._always or name in self._always:
            return True
        if is_mcp:
            if any(
                c.startswith(prefix)
                for c in (command, name)
                for prefix in self._allow
                if prefix
            ):
                return True
        elif name in _COMMAND_TOOLS:
            if any(_argv_prefix_match(command, prefix) for prefix in self._allow if prefix):
                return True
        elif any(command.startswith(prefix) for prefix in self._allow if prefix):
            return True
        display = f"[{label}] {detail}" if label else detail
        with self._lock:
            # Double-checked: another thread may have set the key while we waited.
            if always_key in self._always or name in self._always:
                return True
            decision = self._approver(name, display)
            if decision == "always":
                self._always.add(always_key)
                return True
            return decision == "yes"

    def confirm(self, detail: str, *, label: str = "") -> bool:
        """One-time yes/no gate for a privileged action (e.g. launching a
        background agent with a write or command grant). Honors auto_approve."""
        if self.auto_approve:
            return True
        display = f"[{label}] {detail}" if label else detail
        with self._lock:
            return self._approver("spawn_background_agent", display) in ("yes", "always")

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
