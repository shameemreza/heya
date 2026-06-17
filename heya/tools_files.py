"""Allow-listed file and command tools.

Every path the agent touches resolves through resolve_in_allowlist, the single
security gate: a real absolute path under one of the allowed roots, or ToolError.
Tools take allowed_roots explicitly — no global state — so the agent loop owns
policy and the tools stay trivially testable.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence


class ToolError(Exception):
    """Raised when a tool refuses an operation (sandbox, timeout, missing file)."""


def resolve_in_allowlist(path: Path | str, allowed_roots: Sequence[Path]) -> Path:
    """Resolve path to a real absolute path under one of allowed_roots, or raise.

    strict=False so a not-yet-created target still resolves its existing prefix
    (and any symlinks within it), closing traversal and symlink-escape holes.
    """
    resolved = Path(path).resolve()
    for root in allowed_roots:
        root_resolved = Path(root).resolve()
        if resolved == root_resolved or resolved.is_relative_to(root_resolved):
            return resolved
    raise ToolError(f"Path {resolved} is outside the allowed roots")


def read_file(path: Path | str, *, allowed_roots: Sequence[Path]) -> str:
    """Return the UTF-8 text of a file inside the allow-list."""
    resolved = resolve_in_allowlist(path, allowed_roots)
    try:
        return resolved.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ToolError(f"No such file: {resolved}") from exc
    except IsADirectoryError as exc:
        raise ToolError(f"Is a directory, not a file: {resolved}") from exc


def write_file(path: Path | str, content: str, *, allowed_roots: Sequence[Path]) -> int:
    """Write UTF-8 content inside the allow-list, creating parents. Returns bytes written."""
    resolved = resolve_in_allowlist(path, allowed_roots)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    resolved.write_bytes(data)
    return len(data)


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    exit_code: int


def run_command(
    cmd: str,
    *,
    cwd: Path | str,
    allowed_roots: Sequence[Path],
    timeout: float,
) -> CommandResult:
    """Run a shell command confined to the allow-list. Timeout is required."""
    resolved_cwd = resolve_in_allowlist(cwd, allowed_roots)
    if not resolved_cwd.is_dir():
        raise ToolError(f"cwd is not a directory: {resolved_cwd}")
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=resolved_cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"Command timed out after {timeout}s: {cmd}") from exc
    return CommandResult(stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode)
