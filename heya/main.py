"""The `heya` command: one-shot (heya "task") and interactive (heya) modes."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, TextIO

try:
    from importlib.metadata import version as _pkg_version
    VERSION = _pkg_version("heya-agent")
except Exception:
    VERSION = "0.0.1"

from .agent import Agent, DEFAULT_MAX_ITERS
from .approval import ApprovalPolicy, UiApprover, prompt_stdin
from .config import (
    load_allowed_roots, load_approval_allow, load_browser_headless, load_context_config,
    load_guidance_paths, load_hooks_config, load_mcp_servers, load_memory_path, load_profiles,
    load_routing_config, load_search_config, load_skill_paths, load_wp_path, resolve_profile,
    resolve_weak_profile, load_plugin_paths, load_disabled_plugins,
    load_command_paths, load_agent_paths, load_identity,
    resolve_api_key, load_default_profile, default_config_path,
)
from .init import run_init
from .preflight import check_profile, OK
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
from .ui import UI, should_plain

import uuid


def _git_branch() -> str:
    """Return the current git branch, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def build_parser() -> argparse.ArgumentParser:
    epilog = (
        "examples:\n"
        "  heya                     # interactive session\n"
        "  heya 'fix the failing test'  # one-shot task\n"
    )
    parser = argparse.ArgumentParser(
        prog="heya",
        description="A local-first, tool-using AI agent.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("task", nargs="*", help="Task to run once. Omit for an interactive session.")
    parser.add_argument("--version", action="version", version=f"heya {VERSION}")
    parser.add_argument("--profile", help="Model profile to use (default: resolved from config/env).")
    parser.add_argument("--auto-approve", action="store_true", help="Run write/command tools without prompting.")
    parser.add_argument("--allow", action="append", default=[], metavar="DIR",
                        help="Add an allowed folder (repeatable).")
    parser.add_argument("--no-self-review", action="store_true", help="Disable the scoped self-review pass.")
    parser.add_argument("--max-iters", type=int, default=DEFAULT_MAX_ITERS, help="Max tool-loop iterations per task.")
    return parser


def _handle_slash(text: str, agent: Any, ui: UI) -> bool:
    """Handle a slash command. Returns True to continue the loop, False to quit."""
    cmd = text.strip()
    if cmd == "/quit":
        return False
    if cmd == "/help":
        ui.note(
            "/help      : show this list\n"
            "/quit      : exit\n"
            "/clear     : reset conversation (keep system message)\n"
            "/compact   : compact conversation context\n"
            "/cost      : show token usage\n"
            "/skills    : list loaded skills\n"
            "/agents    : list agent roles\n"
            "/mcp       : list MCP tools"
        )
        return True
    if cmd == "/clear":
        messages = getattr(agent, "messages", None)
        if messages is not None:
            agent.messages = messages[:1]
        ui.note("conversation cleared.")
        return True
    if cmd == "/compact":
        maybe_compact = getattr(agent, "_maybe_compact", None)
        if callable(maybe_compact):
            maybe_compact()
        else:
            ui.note("compact not available.")
        return True
    if cmd == "/cost":
        session = getattr(agent, "session_tokens", 0)
        weak = getattr(agent, "weak_tokens", 0)
        ui.note(f"tokens, session: {session}  weak: {weak}")
        return True
    if cmd == "/skills":
        skills = getattr(agent, "skills", {})
        if skills:
            ui.note("skills: " + ", ".join(sorted(skills)))
        else:
            ui.note("no skills loaded.")
        return True
    if cmd == "/agents":
        roles = getattr(agent, "agent_roles", {})
        if roles:
            ui.note("agents: " + ", ".join(sorted(roles)))
        else:
            ui.note("no agent roles loaded.")
        return True
    if cmd == "/mcp":
        mcp_runtime = getattr(agent, "mcp_runtime", None)
        if mcp_runtime is not None:
            tools = list(getattr(mcp_runtime, "_tools", {}).keys())
            if tools:
                ui.note("mcp tools: " + ", ".join(sorted(tools)))
            else:
                ui.note("no MCP tools connected.")
        else:
            ui.note("no MCP runtime.")
        return True
    ui.note(f"unknown command: {cmd}  (try /help)")
    return True


def _default_make_agent(args: argparse.Namespace, *, ui: "UI | None" = None) -> Agent:
    profiles = load_profiles()
    profile = resolve_profile(args.profile, profiles=profiles, default=load_default_profile())
    weak_profile = resolve_weak_profile(load_routing_config(), profiles)
    roots = list(load_allowed_roots()) + [Path(p).expanduser().resolve() for p in args.allow]
    guidance_sources = (BUNDLED_GUIDANCE_DIR, *load_guidance_paths())
    search_provider = build_search_provider(load_search_config())
    browser_session = BrowserSession(headless=load_browser_headless())
    process_registry = ProcessRegistry()
    playground_session = PlaygroundSession(process_registry, cwd=Path.cwd(), allowed_roots=roots)
    wp_default_root = load_wp_path()
    client = LLMClient(profile, api_key=resolve_api_key(profile))
    weak_client = (
        LLMClient(weak_profile, api_key=resolve_api_key(weak_profile))
        if weak_profile is not None and weak_profile.name != profile.name
        else None
    )
    approver = UiApprover(ui) if ui is not None else prompt_stdin
    approval = ApprovalPolicy(
        auto_approve=args.auto_approve, approver=approver, allow=load_approval_allow()
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
    init_fn: Callable[..., int] = run_init,
    auto_init: bool = False,
) -> int:
    # `heya init` runs the setup wizard, not a task.
    if args.task == ["init"]:
        return init_fn(stream=stdin)
    # Fresh install with no config and no task: greet and set up first.
    # Gated by auto_init so only the real entrypoint (main) triggers it; tests
    # that drive run_cli with injected stdin keep auto_init off and are unaffected.
    if auto_init and not args.task and not default_config_path().exists():
        init_fn(stream=stdin)

    plain = should_plain() or (stdin is not None)
    ui = UI(plain=plain, stream=stdin if stdin is not None else None)

    # Pass the UI to the default agent builder so it can show a colored diff at
    # write approval time.  Custom make_agent callables may not accept ui= and
    # that's fine: we fall back gracefully.
    try:
        agent = make_agent(args, ui=ui)
    except TypeError:
        agent = make_agent(args)

    # Wire agent output through the UI when we have a real agent.
    if hasattr(agent, "on_text"):
        agent.on_text = ui.stream_text
    if hasattr(agent, "_on_tool"):
        agent._on_tool = ui.tool_event

    try:
        model = getattr(getattr(agent, "client", None), "profile", None)
        model_name = getattr(model, "model", "") if model is not None else ""
        profile_name = getattr(model, "name", "") if model is not None else ""
        status = check_profile(model) if model is not None else OK
        HINT = f"Heya v{VERSION} - no model ready. Run `heya init` to set one up."

        if args.task:
            if status != OK:
                ui.error(HINT)
                return 1
            agent.run(" ".join(args.task))
            sys.stdout.write("\n")
            return 0

        # Show banner before the interactive loop.
        if status == OK:
            ui.banner(
                version=VERSION,
                model=model_name,
                profile=profile_name,
                cwd=str(Path.cwd()),
                branch=_git_branch(),
            )
        else:
            ui.error(HINT)

        _exit_words = frozenset({"exit", "quit"})
        while True:
            try:
                line = ui.prompt()
            except EOFError:
                break
            text = line.strip()
            if not text:
                continue
            if text.lower() in _exit_words:
                break
            if text.startswith("/"):
                if not _handle_slash(text, agent, ui):
                    break
                continue
            agent.run(text)
            sys.stdout.write("\n")
        return 0
    finally:
        close = getattr(agent, "close", None)
        if callable(close):
            close()


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser().parse_args(argv), auto_init=True)


if __name__ == "__main__":
    raise SystemExit(main())
