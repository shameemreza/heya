"""WordPress repro tools: read a site's debug.log, drive WP-CLI, boot Playground.

Each tool takes an explicit WP root (the install directory), resolved through the
same allow-list gate as every file tool. Resolution order: the given path, then a
configured [wordpress] default, then the working directory. No disk scanning — when
the target is ambiguous the agent asks the user. wp / npx are invoked only when
present; absent, the tools return install hints and never raise.
"""
from __future__ import annotations

import re
import shlex
import shutil
import time
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


_PLAYGROUND_URL = re.compile(r"https?://(?:localhost|127\.0\.0\.1):\d+")


class PlaygroundSession:
    """A single disposable WordPress Playground server, managed via the registry."""

    def __init__(self, registry, *, cwd: Path, allowed_roots) -> None:
        self._registry = registry
        self._cwd = Path(cwd)
        self._allowed_roots = list(allowed_roots)
        self._id: str | None = None

    def start(self, blueprint=None) -> str:
        if shutil.which("npx") is None:
            return _PLAYGROUND_HINT
        if self._id is not None:  # stop a prior server before starting a new one
            self.stop()
        safe_cwd = resolve_in_allowlist(self._cwd, self._allowed_roots)
        cmd = "npx @wp-playground/cli server"
        if blueprint:
            cmd += f" --blueprint={shlex.quote(str(blueprint))}"
        mp = self._registry.start(cmd, cwd=safe_cwd)
        self._id = mp.id
        for _ in range(40):  # ~10s: wait for the server to print its URL
            match = _PLAYGROUND_URL.search(self._registry.peek(mp.id))
            if match:
                return f"Playground running at {match.group(0)} (process {mp.id}). Hand the URL to browser_navigate, or check_command {mp.id} for logs."
            time.sleep(0.25)
        return f"Playground starting (process {mp.id}); use check_command {mp.id} for the URL."

    def stop(self) -> str:
        if self._id is None:
            return "No playground is running."
        msg = self._registry.kill(self._id)
        self._id = None
        return msg

    def close(self) -> None:
        try:
            self.stop()
        except Exception:
            pass


def resolve_wp_root(path, *, allowed_roots, cwd, default_root=None) -> Path:
    """Resolve the WordPress root: explicit path > config default > cwd, allow-listed."""
    candidate = path or default_root or cwd
    root = resolve_in_allowlist(candidate, allowed_roots)
    if not root.is_dir():
        raise ToolError(f"WordPress root is not a directory: {root}")
    return root


def run_wp_cli(args, path, *, allowed_roots, cwd, default_root=None, timeout) -> str:
    """Run `wp <args> --path=<root>`, confined to the resolved WordPress root."""
    if shutil.which("wp") is None:
        return _WPCLI_HINT
    root = resolve_wp_root(path, allowed_roots=allowed_roots, cwd=cwd, default_root=default_root)
    args = (args or "").strip()
    cmd = f"wp {args}"
    if "--path" not in args:
        cmd += f" --path={shlex.quote(str(root))}"
    result = run_command(cmd, cwd=root, allowed_roots=allowed_roots, timeout=timeout)
    return truncate_output(
        f"exit_code: {result.exit_code}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


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
