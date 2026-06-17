"""Allow-listed file and command tools.

Every path the agent touches resolves through resolve_in_allowlist, the single
security gate: a real absolute path under one of the allowed roots, or ToolError.
Tools take allowed_roots explicitly — no global state — so the agent loop owns
policy and the tools stay trivially testable.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


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
