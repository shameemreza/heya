"""Claude-compatible lifecycle hooks (command type, MVP).

Hooks run user-defined commands at lifecycle points (before/after a tool, etc.).
They are OFF by default (fire_hooks is a no-op until enabled) because they execute
shell. Nothing here raises into the agent loop; a misbehaving hook is a
non-blocking event. No regex. Matchers are alias-aware (a 'Bash' matcher fires on
Heya's run_command)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .skills import CLAUDE_TOOL_ALIASES

# Heya tool name -> the Claude names that alias to it (reverse of CLAUDE_TOOL_ALIASES).
_HEYA_TO_CLAUDE: dict[str, set[str]] = {}
for _claude, _heya in CLAUDE_TOOL_ALIASES.items():
    _HEYA_TO_CLAUDE.setdefault(_heya, set()).add(_claude)


@dataclass(frozen=True)
class HookSpec:
    event: str
    matcher: str
    command: str
    args: tuple[str, ...]
    timeout: float
    source: str


@dataclass(frozen=True)
class HookOutcome:
    block: bool
    message: str
    system_message: str


def parse_hooks_config(data, source: str = "config") -> list[HookSpec]:
    """Read a Claude-style hooks block into command HookSpecs. Accepts either a
    settings dict (with a 'hooks' key) or a bare event->matchers map. Non-command
    handler types and malformed entries are skipped."""
    if not isinstance(data, dict):
        return []
    hooks_map = data.get("hooks", data)
    if not isinstance(hooks_map, dict):
        return []
    specs: list[HookSpec] = []
    for event, matchers in hooks_map.items():
        if not isinstance(matchers, list):
            continue
        for entry in matchers:
            if not isinstance(entry, dict):
                continue
            matcher = str(entry.get("matcher", ""))
            for hook in entry.get("hooks", []) or []:
                if not isinstance(hook, dict) or hook.get("type") != "command":
                    continue
                command = hook.get("command")
                if not command:
                    continue
                raw_args = hook.get("args", [])
                args = tuple(str(a) for a in raw_args) if isinstance(raw_args, list) else ()
                try:
                    timeout = float(hook.get("timeout", 30) or 30)
                except (ValueError, TypeError):
                    timeout = 30.0
                specs.append(HookSpec(str(event), matcher, str(command), args, timeout, source))
    return specs


def collect_hooks(sources: Sequence[Path]) -> dict[str, list[HookSpec]]:
    by_event: dict[str, list[HookSpec]] = {}
    for src in sources:
        src = Path(src)
        if not src.is_file():
            continue
        try:
            data = json.loads(src.read_text(encoding="utf-8", errors="replace"))
        except (ValueError, OSError):
            continue
        for spec in parse_hooks_config(data, source=str(src)):
            by_event.setdefault(spec.event, []).append(spec)
    return by_event


def _names_for(tool_name: str) -> set[str]:
    return {tool_name} | _HEYA_TO_CLAUDE.get(tool_name, set())


def tool_matches(matcher: str, tool_name: str) -> bool:
    m = (matcher or "").strip()
    if m in ("", "*"):
        return True
    parts = {p.strip() for p in m.split("|") if p.strip()}
    candidates = _names_for(tool_name)
    if parts & candidates:
        return True
    return any(p in tool_name for p in parts)  # substring fallback, no regex


def hook_payload(event, *, session_id, cwd, tool_name=None, tool_input=None,
                 tool_output=None) -> dict:
    payload = {"hook_event_name": event, "session_id": session_id, "cwd": cwd}
    if tool_name is not None:
        payload["tool_name"] = tool_name
    if tool_input is not None:
        payload["tool_input"] = tool_input
    if tool_output is not None:
        payload["tool_output"] = tool_output
    return payload


def run_command_hook(spec: HookSpec, payload: dict, *, runner) -> HookOutcome:
    """Run one command hook via the injected runner(spec, *, stdin) -> (exit, out, err).
    Never raises. PreToolUse exit 2 (or stdout {"continue": false}) blocks."""
    try:
        stdin_json = json.dumps(payload)
        exit_code, stdout, stderr = runner(spec, stdin=stdin_json)
    except Exception as exc:  # a runner failure is non-blocking
        return HookOutcome(False, "", f"hook {spec.command} errored: {exc}")
    block = spec.event == "PreToolUse" and exit_code == 2
    system_message = ""
    if (stdout or "").strip():
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                if data.get("continue") is False and spec.event == "PreToolUse":
                    block = True
                system_message = str(data.get("systemMessage", "") or "")
        except ValueError:
            pass
    message = (stderr or "").strip() if block else ""
    return HookOutcome(block, message or system_message, system_message)


def fire_hooks(event, hooks_by_event, payload, *, enabled, runner, tool_name=None,
               on_note=None) -> HookOutcome:
    """Run every matching command hook for `event`. No-op when disabled. PreToolUse
    blocks if any hook blocks. Emits a note per fired hook."""
    if not enabled:
        return HookOutcome(False, "", "")
    for spec in hooks_by_event.get(event, []):
        if event in ("PreToolUse", "PostToolUse") and not tool_matches(spec.matcher, tool_name or ""):
            continue
        if on_note is not None:
            on_note(f"\n[hook {event}: {spec.command}]\n")
        outcome = run_command_hook(spec, payload, runner=runner)
        if outcome.system_message and on_note is not None:
            on_note(f"[hook: {outcome.system_message}]\n")
        if outcome.block:
            return outcome
    return HookOutcome(False, "", "")
