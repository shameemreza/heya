"""WordPress repro tools: read a site's debug.log, drive WP-CLI, boot Playground.

Each tool takes an explicit WP root (the install directory), resolved through the
same allow-list gate as every file tool. Resolution order: the given path, then a
configured [wordpress] default, then the working directory. No disk scanning — when
the target is ambiguous the agent asks the user. wp / npx are invoked only when
present; absent, the tools return install hints and never raise.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .text import truncate_output
from .tools_files import ToolError, resolve_in_allowlist, run_command

_WPCLI_HINT = (
    "WP-CLI is not available. Install it from https://wp-cli.org/ and ensure `wp` is on PATH."
)
_PLAYGROUND_HINT = (
    "WordPress Playground is not available. Install Node, then it runs via "
    "`npx @wp-playground/cli`. See https://wordpress.github.io/wordpress-playground/"
)


def resolve_wp_root(path, *, allowed_roots, cwd, default_root=None) -> Path:
    """Resolve the WordPress root: explicit path > config default > cwd, allow-listed."""
    candidate = path or default_root or cwd
    root = resolve_in_allowlist(candidate, allowed_roots)
    if not root.is_dir():
        raise ToolError(f"WordPress root is not a directory: {root}")
    return root


def read_log(path, *, allowed_roots, cwd, default_root=None, lines=200, grep=None) -> str:
    """Tail wp-content/debug.log under the WP root, with an optional substring filter."""
    root = resolve_wp_root(path, allowed_roots=allowed_roots, cwd=cwd, default_root=default_root)
    log = resolve_in_allowlist(root / "wp-content" / "debug.log", allowed_roots)
    if not log.exists():
        return (
            f"No debug.log found under {root}/wp-content. "
            "Is WP_DEBUG_LOG enabled in wp-config.php?"
        )
    try:
        n = max(1, min(int(lines), 2000))
    except (TypeError, ValueError):
        n = 200
    all_lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    if grep:
        all_lines = [ln for ln in all_lines if grep in ln]
    total = len(all_lines)
    tail = all_lines[-n:]
    header = f"[log: showing last {len(tail)} of {total} lines]"
    return header + "\n" + truncate_output("\n".join(tail))
