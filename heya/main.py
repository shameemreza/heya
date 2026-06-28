"""The `heya` command: one-shot (heya "task") and interactive (heya) modes."""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, TextIO

from .agent import Agent, DEFAULT_MAX_ITERS
from .approval import ApprovalPolicy, prompt_stdin
from .config import (
    load_allowed_roots, load_approval_allow, load_browser_headless, load_context_config,
    load_guidance_paths, load_hooks_config, load_mcp_servers, load_memory_path, load_profiles,
    load_routing_config, load_search_config, load_skill_paths, load_wp_path, resolve_profile,
    resolve_weak_profile, load_plugin_paths, load_disabled_plugins,
    load_command_paths, load_agent_paths, load_identity,
)
from .hooks import collect_hooks
from .plugins import discover_plugins, collect_plugin_skills
from .skills import collect_skills, collect_commands
from .agent_defs import discover_agent_roles
from .llm_client import LLMClient
from .mcp_runtime import MCPRuntime
from .memory import MemoryStore
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
    profiles = load_profiles()
    profile = resolve_profile(args.profile, profiles=profiles)
    weak_profile = resolve_weak_profile(load_routing_config(), profiles)
    roots = list(load_allowed_roots()) + [Path(p).expanduser().resolve() for p in args.allow]
    guidance_sources = (BUNDLED_GUIDANCE_DIR, *load_guidance_paths())
    search_provider = build_search_provider(load_search_config())
    browser_session = BrowserSession(headless=load_browser_headless())
    process_registry = ProcessRegistry()
    playground_session = PlaygroundSession(process_registry, cwd=Path.cwd(), allowed_roots=roots)
    wp_default_root = load_wp_path()
    client = LLMClient(profile)
    weak_client = (
        LLMClient(weak_profile)
        if weak_profile is not None and weak_profile.name != profile.name
        else None
    )
    approval = ApprovalPolicy(
        auto_approve=args.auto_approve, approver=prompt_stdin, allow=load_approval_allow()
    )
    mcp_runtime = MCPRuntime(
        load_mcp_servers(), allowed_roots=roots,
        llm_client=client,
        sampling_approver=lambda server, preview: approval.check_sampling(server, preview),
    )
    mcp_runtime.connect_all()
    ctx = load_context_config()

    def on_text(chunk: str) -> None:
        sys.stdout.write(chunk)
        sys.stdout.flush()

    def memory_notify(line: str) -> None:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    memory_store = MemoryStore(load_memory_path(), notify=memory_notify)
    user_skills = collect_skills(load_skill_paths())
    disabled = load_disabled_plugins()
    plugins = {n: p for n, p in discover_plugins(load_plugin_paths()).items() if n not in disabled}
    plugin_skills = collect_plugin_skills(plugins)
    skills = {**plugin_skills, **user_skills}  # a user's own same-named skill wins
    command_skills = collect_commands(load_command_paths())
    plugin_command_skills = {f"{p.name}:{k}": v for p in plugins.values()
                             for k, v in collect_commands([p.root / "commands"]).items()}
    skills = {**command_skills, **plugin_command_skills, **skills}  # user/explicit skills still win
    agent_roles = discover_agent_roles(load_agent_paths())
    plugin_agent_roles = {f"{p.name}:{k}": v for p in plugins.values()
                          for k, v in discover_agent_roles([p.root / "agents"]).items()}
    agent_roles = {**plugin_agent_roles, **agent_roles}  # user agents win

    hooks_enabled, hook_sources = load_hooks_config()
    plugin_hook_files = [p.root / "hooks" / "hooks.json" for p in plugins.values()]
    hooks = collect_hooks([*hook_sources, *plugin_hook_files])
    session_id = uuid.uuid4().hex
    identity = load_identity()

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
        mcp_runtime=mcp_runtime,
        memory_store=memory_store,
        context_window=profile.context_window,
        compaction_threshold=ctx.threshold,
        reserve_tokens=ctx.reserve_tokens,
        keep_recent_tokens=ctx.keep_recent_tokens,
        task_token_budget=ctx.task_token_budget,
        weak_client=weak_client,
        skills=skills,
        agent_roles=agent_roles,
        hooks=hooks,
        hooks_enabled=hooks_enabled,
        session_id=session_id,
        identity=identity,
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
