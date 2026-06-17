"""The `heya` command: one-shot (heya "task") and interactive (heya) modes."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable, TextIO

from .agent import Agent, DEFAULT_MAX_ITERS
from .approval import ApprovalPolicy, prompt_stdin
from .config import (
    load_allowed_roots, load_approval_allow, load_browser_headless, load_guidance_paths,
    load_profiles, load_search_config, load_wp_path, resolve_profile,
)
from .llm_client import LLMClient
from .process import ProcessRegistry
from .tools_browser import BrowserSession
from .tools_wp import PlaygroundSession
from .tools_guidance import BUNDLED_GUIDANCE_DIR
from .tools_web import build_search_provider

EXIT_WORDS = frozenset({"exit", "quit"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="heya", description="A local-first, tool-using AI agent.")
    parser.add_argument("task", nargs="*", help="Task to run once. Omit for an interactive session.")
    parser.add_argument("--profile", help="Model profile to use (default: resolved from config/env).")
    parser.add_argument("--auto-approve", action="store_true", help="Run write/command tools without prompting.")
    parser.add_argument("--allow", action="append", default=[], metavar="DIR",
                        help="Add an allowed folder (repeatable).")
    parser.add_argument("--no-self-review", action="store_true", help="Disable the scoped self-review pass.")
    parser.add_argument("--max-iters", type=int, default=DEFAULT_MAX_ITERS, help="Max tool-loop iterations per task.")
    return parser


def _default_make_agent(args: argparse.Namespace) -> Agent:
    profile = resolve_profile(args.profile, profiles=load_profiles())
    roots = list(load_allowed_roots()) + [Path(p).expanduser().resolve() for p in args.allow]
    guidance_sources = (BUNDLED_GUIDANCE_DIR, *load_guidance_paths())
    search_provider = build_search_provider(load_search_config())
    browser_session = BrowserSession(headless=load_browser_headless())
    process_registry = ProcessRegistry()
    playground_session = PlaygroundSession(process_registry, cwd=Path.cwd(), allowed_roots=roots)
    wp_default_root = load_wp_path()
    client = LLMClient(profile)
    approval = ApprovalPolicy(
        auto_approve=args.auto_approve, approver=prompt_stdin, allow=load_approval_allow()
    )

    def on_text(chunk: str) -> None:
        sys.stdout.write(chunk)
        sys.stdout.flush()

    return Agent(
        client,
        allowed_roots=roots,
        cwd=Path.cwd(),
        approval=approval,
        on_text=on_text,
        self_review=not args.no_self_review,
        max_iters=args.max_iters,
        guidance_sources=guidance_sources,
        search_provider=search_provider,
        browser_session=browser_session,
        process_registry=process_registry,
        playground_session=playground_session,
        wp_default_root=wp_default_root,
    )


def run_cli(
    args: argparse.Namespace,
    *,
    make_agent: Callable[[argparse.Namespace], Any] = _default_make_agent,
    stdin: TextIO | None = None,
) -> int:
    agent = make_agent(args)
    # The agent streams its reply live via on_text; run_cli only ends each
    # turn's line, so the answer is printed once (not streamed and re-printed).
    try:
        if args.task:
            agent.run(" ".join(args.task))
            sys.stdout.write("\n")
            return 0
        stream = stdin if stdin is not None else sys.stdin
        while True:
            try:
                line = stream.readline()
            except (EOFError, KeyboardInterrupt):
                break
            if line == "":  # EOF
                break
            text = line.strip()
            if not text:
                continue
            if text.lower() in EXIT_WORDS:
                break
            agent.run(text)
            sys.stdout.write("\n")
        return 0
    finally:
        close = getattr(agent, "close", None)
        if callable(close):
            close()


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
