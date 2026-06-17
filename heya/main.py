"""The `heya` command: one-shot (heya "task") and interactive (heya) modes."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable, TextIO

from .agent import Agent, DEFAULT_MAX_ITERS
from .approval import ApprovalPolicy, prompt_stdin
from .config import load_allowed_roots, load_profiles, resolve_profile
from .llm_client import LLMClient

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
    client = LLMClient(profile)
    approval = ApprovalPolicy(auto_approve=args.auto_approve, approver=prompt_stdin)

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
    )


def run_cli(
    args: argparse.Namespace,
    *,
    make_agent: Callable[[argparse.Namespace], Any] = _default_make_agent,
    stdin: TextIO | None = None,
) -> int:
    agent = make_agent(args)
    if args.task:
        answer = agent.run(" ".join(args.task))
        print(answer)
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
        answer = agent.run(text)
        print(answer)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
