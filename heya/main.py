"""The `heya` command: one-shot (heya "task") and interactive (heya) modes."""
from __future__ import annotations

import argparse
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

try:
    from importlib.metadata import version as _pkg_version
    VERSION = _pkg_version("heya-agent")
except Exception:
    VERSION = "0.0.2"

from .agent import Agent, DEFAULT_MAX_ITERS
from .project import load_project_instructions
from .approval import ApprovalPolicy, UiApprover, prompt_stdin
from .config import (
    load_allowed_roots, load_approval_allow, load_browser_headless, load_context_config,
    load_guidance_paths, load_hooks_config, load_mcp_servers, load_memory_path, load_profiles,
    load_routing_config, load_search_config, load_skill_paths, load_wp_path, resolve_profile,
    resolve_weak_profile, load_plugin_paths, load_disabled_plugins,
    load_command_paths, load_agent_paths, load_identity,
    resolve_api_key, load_default_profile, default_config_path, model_supports_vision,
    load_project_instructions_enabled, load_agent_config, load_update_config,
    load_wordpress_config, load_web_config,
)
from .credentials import load_key
from .wpsite import build_wp_connector
from .update import run_update, update_notice
from .init import run_init
from .wpconnect import run_wp_connect
from .preflight import check_profile, OK
from .hooks import collect_hooks
from .plugins import discover_plugins, collect_plugin_skills
from .skills import collect_skills, collect_commands
from .agent_defs import discover_agent_roles
from .llm_client import LLMClient
from .mcp_runtime import MCPRuntime
from .memory import MemoryStore
from .background import BackgroundRegistry
from .process import ProcessRegistry
from .tools_browser import BrowserSession
from .tools_wp import PlaygroundSession
from .tools_guidance import BUNDLED_GUIDANCE_DIR
from .tools_web import build_search_provider
from .ui import UI, should_plain
from . import sessions
from . import attachments

import uuid


def _build_turn_content(text, agent, ui):
    """Build message content from @mentions: text files inlined, images as base64.

    Returns either a plain string (no mentions) or a list of content blocks.
    Shows warnings for read failures and non-vision model image attachments.
    """
    content, info = attachments.build_user_content(
        text, allowed_roots=getattr(agent, "allowed_roots", []),
        cwd=getattr(agent, "cwd", "."))
    for note in info.get("notes", []):
        ui.note(note)
    if info.get("has_image"):
        prof = getattr(getattr(agent, "client", None), "profile", None)
        if prof is not None and not model_supports_vision(prof):
            ui.note("this model cannot see images. switch to a vision model with /model.")
    return content


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_snapshot(agent, *, profile_name, created, updated, title=None) -> dict:
    messages = getattr(agent, "messages", [])
    return {
        "id": getattr(agent, "session_id", ""),
        "title": title or sessions.derive_title(messages),
        "created": created,
        "updated": updated,
        "profile": profile_name,
        "cwd": str(getattr(agent, "cwd", "")),
        "session_tokens": getattr(agent, "session_tokens", 0),
        "weak_tokens": getattr(agent, "weak_tokens", 0),
        "messages": messages,
        "background": (agent.background_registry.snapshot()
                       if getattr(agent, "background_registry", None) is not None else []),
    }


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
    parser.add_argument("--continue", dest="continue_", action="store_true",
                        help="Resume the most recent session.")
    parser.add_argument("--resume", nargs="?", const="__latest__", default=None,
                        metavar="ID", help="Resume a session by id (or the latest if omitted).")
    return parser


def _handle_slash(text: str, agent: Any, ui: UI, *, profiles=None,
                  sessions_dir=None, created="", now=None) -> bool:
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
            "/mcp       : list MCP tools\n"
            "/model     : show or switch the model profile (/model <name>)\n"
            "/sessions  : list saved sessions\n"
            "/resume    : resume a session (/resume <id>)\n"
            "/save      : save now, optionally name it (/save <title>)\n"
            "/new       : start a fresh session\n"
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
    if cmd == "/model" or cmd.startswith("/model "):
        name = cmd[len("/model"):].strip()
        prof = getattr(getattr(agent, "client", None), "profile", None)
        if not name:
            ui.note(f"model: {getattr(prof, 'name', '?')} ({getattr(prof, 'model', '?')})")
            return True
        profiles = profiles or {}
        if not profiles:
            ui.note("no profiles loaded.")
            return True
        if name not in profiles:
            ui.note("unknown profile. available: " + ", ".join(sorted(profiles)))
            return True
        target = profiles[name]
        agent.client = LLMClient(target, api_key=resolve_api_key(target))
        if hasattr(agent, "context_window"):
            agent.context_window = target.context_window
        ui.note(f"switched to {target.name} ({target.model}).")
        return True
    if cmd == "/new":
        msgs = getattr(agent, "messages", None)
        if msgs is not None:
            agent.messages = msgs[:1]
        agent.session_id = uuid.uuid4().hex
        ui.note("started a new session.")
        return True
    if cmd == "/sessions":
        items = sessions.list_sessions(sessions_dir=sessions_dir)
        if not items:
            ui.note("no saved sessions.")
            return True
        lines = [f"  {s.get('id','')[:8]}  {s.get('title','')}  ({s.get('messages',0)} msgs)" for s in items]
        ui.note("sessions:\n" + "\n".join(lines))
        return True
    if cmd == "/resume" or cmd.startswith("/resume "):
        sid = cmd[len("/resume"):].strip()
        if not sid:
            sid = sessions.latest_session_id(sessions_dir=sessions_dir)
        data = sessions.load_session(sid, sessions_dir=sessions_dir) if sid else None
        if not data:
            ui.note("no such session.")
            return True
        agent.messages = data.get("messages", getattr(agent, "messages", []))
        agent.session_id = data.get("id", getattr(agent, "session_id", ""))
        agent.session_tokens = data.get("session_tokens", 0)
        agent.weak_tokens = data.get("weak_tokens", 0)
        ui.note(f"resumed session {agent.session_id[:8]}.")
        return True
    if cmd == "/save" or cmd.startswith("/save "):
        title = cmd[len("/save"):].strip() or None
        prof = getattr(getattr(agent, "client", None), "profile", None)
        snap = _session_snapshot(agent, profile_name=getattr(prof, "name", ""),
                                 created=created, updated=(now or _now)(), title=title)
        sessions.save_session(snap, sessions_dir=sessions_dir)
        ui.note("saved.")
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
    web_cfg = load_web_config()
    browser_session = BrowserSession(headless=load_browser_headless())
    process_registry = ProcessRegistry()
    background_registry = BackgroundRegistry(max_concurrent=load_agent_config().max_background)
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
    project_instructions = load_project_instructions(
        Path.cwd(), enabled=load_project_instructions_enabled())

    wp_connector = None
    wp_cfg = load_wordpress_config()
    if wp_cfg is not None:
        if wp_cfg.is_allowed_env():
            wp_connector = build_wp_connector(wp_cfg, load_key(wp_cfg.password_key))
            if wp_connector is None and ui is not None:
                ui.note("WordPress site is configured but has no stored password. Run `heya wp connect`.")
        elif ui is not None:
            ui.note(f"WordPress site env is {wp_cfg.env!r}; the site tools need dev or staging.")

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
        project_instructions=project_instructions,
        background_registry=background_registry,
        write_guard=(lambda name, call_args:
                     background_registry.check_write(call_args.get("path", ""), "main")
                     if name == "write_file" else None),
        wp_connector=wp_connector,
        web_block_metadata=web_cfg.block_metadata,
        status_cb=getattr(ui, "status", None),
    )


def run_cli(
    args: argparse.Namespace,
    *,
    make_agent: Callable[[argparse.Namespace], Any] = _default_make_agent,
    stdin: TextIO | None = None,
    init_fn: Callable[..., int] = run_init,
    update_fn: Callable[..., int] = run_update,
    wp_connect_fn: Callable[..., int] = run_wp_connect,
    auto_init: bool = False,
) -> int:
    # `heya init` runs the setup wizard, not a task.
    if args.task == ["init"]:
        return init_fn(stream=stdin)
    # `heya update` upgrades the installed package.
    if args.task == ["update"]:
        return update_fn()
    # `heya wp connect` runs the WordPress site setup flow.
    if args.task == ["wp", "connect"]:
        return wp_connect_fn(stream=stdin)
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

    want = getattr(args, "resume", None)
    if getattr(args, "continue_", False) and want is None:
        want = "__latest__"
    if want is not None:
        sid = sessions.latest_session_id() if want == "__latest__" else want
        data = sessions.load_session(sid) if sid else None
        if data:
            agent.messages = data.get("messages", getattr(agent, "messages", []))
            agent.session_id = data.get("id", getattr(agent, "session_id", ""))
            agent.session_tokens = data.get("session_tokens", 0)
            agent.weak_tokens = data.get("weak_tokens", 0)
        else:
            ui.note("no session to resume; starting fresh.")

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
            try:
                agent.run(_build_turn_content(" ".join(args.task), agent, ui))
            except KeyboardInterrupt:
                ui.error("Interrupted.")
                return 130
            except Exception as exc:  # noqa: BLE001 - keep the CLI from crashing on API/tool errors
                ui.error(f"Error: {exc}")
                return 1
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
            try:
                newer = update_notice(VERSION, enabled=load_update_config().check)
                if newer:
                    ui.note(f"A newer Heya ({newer}) is available. Run `heya update`.")
            except Exception:
                pass
        else:
            ui.error(HINT)
            return 1

        profiles = load_profiles()
        sessions_dir = sessions.default_sessions_dir()
        session_created = _now()

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
                if getattr(agent, "background_registry", None) is not None:
                    running = agent.background_registry.running_ids()
                    if running:
                        ui.note(f"Ending {len(running)} background agent(s) still running: "
                                f"{', '.join(running)}. They do not survive quitting.")
                break
            if text.startswith("/"):
                if not _handle_slash(text, agent, ui, profiles=profiles,
                                     sessions_dir=sessions_dir, created=session_created):
                    break
                continue
            notes = ""
            try:
                if getattr(agent, "background_registry", None) is not None:
                    done = agent.background_registry.drain_finished()
                    for a in done:
                        ui.note(f"{a.id} {a.status}: {a.task[:60]}. Use collect_agent('{a.id}').")
                    if done:
                        notes = ("[background update] finished: "
                                 + ", ".join(f"{a.id} ({a.status})" for a in done)
                                 + ". Use collect_agent to read results.\n")
            except Exception:
                pass
            cancel = getattr(agent, "cancel", None)

            def _on_sigint(signum, frame):
                if cancel is not None:
                    cancel.set()

            try:
                prev = signal.signal(signal.SIGINT, _on_sigint)
                _sigint_installed = True
            except ValueError:
                prev = None
                _sigint_installed = False

            try:
                agent.run(_build_turn_content(notes + text, agent, ui))
            except KeyboardInterrupt:
                ui.error("Interrupted.")
            except Exception as exc:  # noqa: BLE001 - keep the REPL alive on API/tool errors
                ui.error(f"Error: {exc}")
            finally:
                if _sigint_installed:
                    signal.signal(signal.SIGINT, prev)
                if cancel is not None:
                    cancel.clear()

            sys.stdout.write("\n")
            snap = _session_snapshot(agent, profile_name=profile_name,
                                     created=session_created, updated=_now())
            sessions.save_session(snap, sessions_dir=sessions_dir)
        return 0
    finally:
        close = getattr(agent, "close", None)
        if callable(close):
            close()


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser().parse_args(argv), auto_init=True)


if __name__ == "__main__":
    raise SystemExit(main())
