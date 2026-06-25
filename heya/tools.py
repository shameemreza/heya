"""Bridge between model tool-calls and the Phase 2 file/command functions.

TOOL_SCHEMAS is the OpenAI `tools` array sent to the model. dispatch_tool runs a
single tool-call and always returns a string — ToolError, bad JSON, and unknown
tools become readable strings, never exceptions, so the agent loop can feed a
failure back to the model instead of crashing.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from .memory import MEMORY_TYPES
from .subagents import ROLES as _ROLES
from .text import truncate_output
from .tools_files import ToolError, read_file, resolve_in_allowlist, run_command, write_file
from .tools_guidance import read_guidance as _read_guidance
from .tools_mcp import MCP_PREFIX, build_reverse_map, mcp_tool_name, parse_mcp_name, _MAX_DESC
from .tools_web import web_fetch, web_search
from .tools_wp import read_log, run_wp_cli

_MCP_RESOURCE_SCHEMAS = [
    {"type": "function", "function": {
        "name": "mcp_list_resources",
        "description": "List data resources available from connected MCP servers (server, uri, name, description).",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "mcp_read_resource",
        "description": "Read one MCP resource's contents into context.",
        "parameters": {"type": "object",
            "properties": {"server": {"type": "string"}, "uri": {"type": "string"}},
            "required": ["server", "uri"]},
    }},
]
_MCP_PROMPT_SCHEMAS = [
    {"type": "function", "function": {
        "name": "mcp_list_prompts",
        "description": "List prompt templates available from connected MCP servers (server, name, description, arguments).",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "mcp_get_prompt",
        "description": "Expand an MCP prompt template to its messages.",
        "parameters": {"type": "object",
            "properties": {"server": {"type": "string"}, "name": {"type": "string"},
                "arguments": {"type": "object"}},
            "required": ["server", "name"]},
    }},
]

_SPAWN_AGENT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "spawn_agent",
        "description": (
            "Delegate a self-contained task to a fresh sub-agent that runs to "
            "completion and returns only its final report. The sub-agent sees NONE "
            "of this conversation, so describe everything it needs in `task`. "
            "Optionally specialize it with `role` and extra `instructions`."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string",
                         "description": "Self-contained task for the sub-agent."},
                "role": {"type": "string", "enum": sorted(_ROLES),
                         "description": "Optional specialization."},
                "instructions": {"type": "string",
                                 "description": "Optional extra focusing guidance."},
            },
            "required": ["task"],
        },
    },
}

_SPAWN_AGENTS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "spawn_agents",
        "description": (
            "Fan out several READ-ONLY sub-agents to run in parallel — each on a "
            "self-contained task — and get all their reports back at once to "
            "synthesize. Use for independent research/review/analysis you want done "
            "concurrently (e.g. review a diff for bugs, security, and style at the "
            "same time). Each sub-agent is read-only (no file writes, no browser, no "
            "Playground) and sees none of this conversation, so give each a complete, "
            "DISTINCT task to avoid duplicated work. For writing or browser work, use "
            "spawn_agent (one at a time) instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "The parallel tasks; each runs in its own read-only sub-agent.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "task": {"type": "string",
                                     "description": "Self-contained task for one sub-agent."},
                            "role": {"type": "string", "enum": sorted(_ROLES),
                                     "description": "Optional specialization."},
                            "instructions": {"type": "string",
                                             "description": "Optional extra focusing guidance."},
                        },
                        "required": ["task"],
                    },
                },
            },
            "required": ["tasks"],
        },
    },
}

_MEMORY_SCHEMAS = [
    {"type": "function", "function": {
        "name": "remember",
        "description": (
            "Save a durable fact worth remembering across sessions: the user's stable "
            "preferences, a project fact, feedback/correction about how to work, or a "
            "reference pointer. Check what you already remember first and use "
            "update_memory instead of duplicating. Do not store secrets, credentials, "
            "or anything already in the repo."),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Short kebab-case identifier."},
            "description": {"type": "string", "description": "One-line summary (shown in the index)."},
            "type": {"type": "string", "enum": list(MEMORY_TYPES)},
            "content": {"type": "string", "description": "The fact itself."},
        }, "required": ["name", "description", "type", "content"]}}},
    {"type": "function", "function": {
        "name": "update_memory",
        "description": "Revise an existing memory when a fact changes or to correct it.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "content": {"type": "string"},
        }, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "forget",
        "description": "Delete a memory that is no longer true or useful.",
        "parameters": {"type": "object",
            "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "read_memory",
        "description": "Read the full text of one remembered note by name.",
        "parameters": {"type": "object",
            "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
]

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the UTF-8 text of a file inside the allowed folders.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path to read."}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write UTF-8 content to a file inside the allowed folders, creating parent directories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write."},
                    "content": {"type": "string", "description": "Full new contents of the file."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command in the working directory (inside the allowed folders). Returns stdout, stderr, and exit code. Set background=true for a long-lived process (dev server, watcher) — it returns a process id immediately; read it later with check_command and stop it with kill_command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "The shell command to run."},
                    "background": {"type": "boolean", "description": "Run without waiting; returns a process id. Default false."},
                },
                "required": ["cmd"],
            },
        },
    },
    {"type": "function", "function": {
        "name": "check_command",
        "description": "Read new output from a background process started with run_command(background=true), by its id.",
        "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {
        "name": "kill_command",
        "description": "Stop a background process by its id.",
        "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {
        "name": "read_log",
        "description": "Tail a WordPress site's wp-content/debug.log. Give the site's root as `path` (or rely on the configured default). Use `grep` to filter (e.g. 'Fatal error') and `lines` for how many.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "WordPress root directory. Optional if a default is configured."},
            "lines": {"type": "integer", "description": "How many trailing lines (default 200, max 2000)."},
            "grep": {"type": "string", "description": "Only lines containing this substring."},
        }, "required": []}}},
    {"type": "function", "function": {
        "name": "run_wp_cli",
        "description": "Run a WP-CLI command against a WordPress site. Give the WP-CLI arguments in `args` (e.g. 'plugin list', 'option get siteurl'); the site root goes in `path` (or the configured default). Dev/staging only — back up before destructive ops (db reset, site empty).",
        "parameters": {"type": "object", "properties": {
            "args": {"type": "string", "description": "WP-CLI arguments after `wp`, e.g. 'plugin list'."},
            "path": {"type": "string", "description": "WordPress root directory. Optional if a default is configured."},
        }, "required": ["args"]}}},
    {
        "type": "function",
        "function": {
            "name": "read_guidance",
            "description": (
                "List available internal guidance, or read one by name. Consult relevant "
                "guidance before related work — it is the source of truth for standards and voice. "
                "Call with no name to see what is available."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Guidance name to read. Omit to list all."}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current or external information. Returns a numbered list of results (title, URL, snippet).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query."},
                    "max_results": {"type": "integer", "description": "How many results (default 5)."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch an http/https web page and return its readable text content.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "The page URL to fetch."}},
                "required": ["url"],
            },
        },
    },
    {"type": "function", "function": {
        "name": "wp_playground",
        "description": "Boot a disposable clean WordPress (WASM) to reproduce on, or stop it. action='start' returns a local URL you can drive with the browser tools; action='stop' tears it down. Optional `blueprint` (path or JSON) sets the WP version and plugins.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "description": "'start' (default) or 'stop'."},
            "blueprint": {"type": "string", "description": "Optional Playground blueprint path or JSON."},
        }, "required": []}}},
    {"type": "function", "function": {
        "name": "browser_navigate",
        "description": "Open a URL in the browser and return the page's readable text. Starts the browser if needed.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "browser_snapshot",
        "description": "Return the current browser page's readable text (re-read after an action).",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "browser_click",
        "description": "Click an element on the current page by its visible text, role name, or a CSS selector.",
        "parameters": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}}},
    {"type": "function", "function": {
        "name": "browser_type",
        "description": "Type text into a form field identified by its label, placeholder, or a CSS selector.",
        "parameters": {"type": "object", "properties": {"target": {"type": "string"}, "text": {"type": "string"}}, "required": ["target", "text"]}}},
    {"type": "function", "function": {
        "name": "browser_screenshot",
        "description": "Save a full-page PNG screenshot of the current page. Path must be inside an allowed folder.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Where to save (optional; defaults to the working directory)."}}, "required": []}}},
    {"type": "function", "function": {
        "name": "browser_evidence",
        "description": "Return console messages and network errors captured during this browser session.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]


def build_tool_schemas(mcp_runtime=None, *, can_spawn: bool = False, with_memory: bool = False) -> list[dict]:
    """Native tools plus, when a runtime is connected, one schema per MCP tool.

    Includes the spawn tools only when `can_spawn` (depth-0 agents) and the memory
    tools only when `with_memory` (the root agent, which holds the store).
    """
    extras: list[dict] = []
    if can_spawn:
        extras += [_SPAWN_AGENT_SCHEMA, _SPAWN_AGENTS_SCHEMA]
    if with_memory:
        extras += _MEMORY_SCHEMAS
    base = TOOL_SCHEMAS + extras if extras else TOOL_SCHEMAS
    if mcp_runtime is None:
        return base
    extra: list[dict] = []
    for server, tool in mcp_runtime.list_tools():
        description = (tool.get("description") or "")[:_MAX_DESC]
        extra.append({
            "type": "function",
            "function": {
                "name": mcp_tool_name(server, tool["name"]),
                "description": description,
                "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
            },
        })
    if mcp_runtime.has_resources():
        extra += _MCP_RESOURCE_SCHEMAS
    if mcp_runtime.has_prompts():
        extra += _MCP_PROMPT_SCHEMAS
    return base + extra


def dispatch_tool(
    name: str,
    arguments: str,
    *,
    allowed_roots: Sequence[Path],
    cwd: Path,
    timeout: float,
    guidance_sources: Sequence[Path] = (),
    search_provider=None,
    browser_session=None,
    process_registry=None,
    wp_default_root=None,
    playground_session=None,
    mcp_runtime=None,
    spawn_fn=None,
    spawn_agents_fn=None,
    memory_store=None,
) -> str:
    """Run one model tool-call. Returns a string result (errors included)."""
    try:
        args = json.loads(arguments) if arguments.strip() else {}
    except json.JSONDecodeError as exc:
        return f"Error: could not parse tool arguments as JSON: {exc}"
    if not isinstance(args, dict):
        return f"Error: tool arguments must be a JSON object, got {type(args).__name__}."
    try:
        if name.startswith(MCP_PREFIX):
            if mcp_runtime is None:
                return f"Error: unknown tool {name!r}."
            target = parse_mcp_name(name, build_reverse_map(mcp_runtime.list_tools()))
            if target is None:
                return f"Error: unknown tool {name!r}."
            server, tool = target
            return truncate_output(mcp_runtime.call_tool(server, tool, args))
        if name == "mcp_list_resources":
            if mcp_runtime is None:
                return f"Error: unknown tool {name!r}."
            rows = mcp_runtime.list_resources()
            if not rows:
                return "No connected MCP server provides resources."
            return truncate_output("\n".join(
                f"{srv}\t{r['uri']}\t{r.get('name','')}\t{r.get('description','')}" for srv, r in rows))
        if name == "mcp_read_resource":
            if mcp_runtime is None:
                return f"Error: unknown tool {name!r}."
            return truncate_output(mcp_runtime.read_resource(args["server"], args["uri"]))
        if name == "mcp_list_prompts":
            if mcp_runtime is None:
                return f"Error: unknown tool {name!r}."
            rows = mcp_runtime.list_prompts()
            if not rows:
                return "No connected MCP server provides prompts."
            return truncate_output("\n".join(
                f"{srv}\t{p['name']}\t{p.get('description','')}\targs={p.get('arguments',[])}" for srv, p in rows))
        if name == "mcp_get_prompt":
            if mcp_runtime is None:
                return f"Error: unknown tool {name!r}."
            return truncate_output(
                mcp_runtime.get_prompt(args["server"], args["name"], args.get("arguments") or {}))
        if name == "read_file":
            return truncate_output(read_file(args["path"], allowed_roots=allowed_roots))
        if name == "write_file":
            n = write_file(args["path"], args["content"], allowed_roots=allowed_roots)
            return f"Wrote {n} bytes to {args['path']}."
        if name == "run_command":
            if args.get("background"):
                if process_registry is None:
                    raise ToolError("background processes are not available in this context")
                safe_cwd = resolve_in_allowlist(cwd, allowed_roots)
                mp = process_registry.start(args["cmd"], cwd=safe_cwd)
                return f"Started background process {mp.id} (pid {mp.pid}). Use check_command {mp.id!r} to read output, kill_command to stop it."
            result = run_command(args["cmd"], cwd=cwd, allowed_roots=allowed_roots, timeout=timeout)
            return truncate_output(
                f"exit_code: {result.exit_code}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
        if name == "check_command":
            if process_registry is None:
                raise ToolError("background processes are not available in this context")
            return truncate_output(process_registry.poll(args["id"]))
        if name == "kill_command":
            if process_registry is None:
                raise ToolError("background processes are not available in this context")
            return process_registry.kill(args["id"])
        if name == "read_guidance":
            return _read_guidance(args.get("name") or None, sources=guidance_sources)
        if name == "web_search":
            try:
                max_results = int(args.get("max_results", 5))
            except (TypeError, ValueError):
                max_results = 5  # keep dispatch_tool's never-raise contract on bad input
            max_results = max(1, max_results)  # uniform across providers; never zero/negative
            return web_search(args["query"], provider=search_provider, max_results=max_results)
        if name == "web_fetch":
            return web_fetch(args["url"], timeout=timeout)
        if name in (
            "browser_navigate", "browser_snapshot", "browser_click",
            "browser_type", "browser_screenshot", "browser_evidence",
        ):
            if browser_session is None:
                raise ToolError("the browser is not available in this context")
            if name == "browser_navigate":
                return browser_session.navigate(args["url"])
            if name == "browser_snapshot":
                return browser_session.snapshot()
            if name == "browser_click":
                return browser_session.click(args["target"])
            if name == "browser_type":
                return browser_session.type_text(args["target"], args["text"])
            if name == "browser_evidence":
                return browser_session.evidence()
            if name == "browser_screenshot":
                raw = args.get("path") or str(Path(cwd) / "heya-screenshot.png")
                safe = resolve_in_allowlist(raw, allowed_roots)
                return browser_session.screenshot(safe)
        if name == "wp_playground":
            if playground_session is None:
                raise ToolError("the WordPress Playground is not available in this context")
            if args.get("action") == "stop":
                return playground_session.stop()
            return playground_session.start(args.get("blueprint"))
        if name == "read_log":
            return read_log(
                args.get("path"), allowed_roots=allowed_roots, cwd=cwd,
                default_root=wp_default_root, lines=args.get("lines", 200), grep=args.get("grep"),
            )
        if name == "run_wp_cli":
            return run_wp_cli(
                args["args"], args.get("path"), allowed_roots=allowed_roots,
                cwd=cwd, default_root=wp_default_root, timeout=timeout,
            )
        if name == "spawn_agent":
            if spawn_fn is None:
                return f"Error: unknown tool {name!r}."
            task = args["task"]  # KeyError → handled below as missing-arg
            return truncate_output(
                spawn_fn(task, args.get("role"), args.get("instructions"))
            )
        if name == "spawn_agents":
            if spawn_agents_fn is None:
                return f"Error: unknown tool {name!r}."
            return spawn_agents_fn(args["tasks"])  # method truncates per report itself
        if name in ("remember", "update_memory", "forget", "read_memory"):
            if memory_store is None:
                return f"Error: unknown tool {name!r}."
            if name == "remember":
                return memory_store.save(args["name"], args["description"], args["type"], args["content"])
            if name == "update_memory":
                return memory_store.update(
                    args["name"], description=args.get("description"), content=args.get("content"))
            if name == "forget":
                return memory_store.delete(args["name"])
            return memory_store.read(args["name"])  # read_memory
        return f"Error: unknown tool {name!r}."
    except ToolError as exc:
        return f"Error: {exc}"
    except KeyError as exc:
        return f"Error: missing required argument {exc} for tool {name!r}."


def describe_call(name: str, arguments: str) -> str:
    """One-line human summary of a tool-call, for approval prompts."""
    try:
        args = json.loads(arguments) if arguments.strip() else {}
    except json.JSONDecodeError:
        args = {}
    if name == "write_file":
        return f"write_file → {args.get('path', '?')}"
    if name == "run_command":
        bg = " (background)" if args.get("background") else ""
        return f"run_command{bg} → {args.get('cmd', '?')}"
    if name == "check_command":
        return f"check_command → {args.get('id', '?')}"
    if name == "kill_command":
        return f"kill_command → {args.get('id', '?')}"
    if name == "read_file":
        return f"read_file → {args.get('path', '?')}"
    if name == "read_guidance":
        return f"read_guidance → {args.get('name') or '(list)'}"
    if name == "web_search":
        return f"web_search → {args.get('query', '?')}"
    if name == "web_fetch":
        return f"web_fetch → {args.get('url', '?')}"
    if name == "browser_navigate":
        return f"browser_navigate → {args.get('url', '?')}"
    if name == "browser_click":
        return f"browser_click → {args.get('target', '?')}"
    if name == "browser_type":
        return f"browser_type → {args.get('target', '?')}"
    if name in ("browser_snapshot", "browser_screenshot", "browser_evidence"):
        return name
    if name == "wp_playground":
        return f"wp_playground → {args.get('action') or 'start'}"
    if name == "read_log":
        return f"read_log → {args.get('path') or '(default site)'}"
    if name == "run_wp_cli":
        return f"run_wp_cli → wp {args.get('args', '?')}"
    if name == "mcp_read_resource":
        return f"mcp_read_resource → read resource {args.get('uri','?')} from {args.get('server','?')}"
    if name == "mcp_get_prompt":
        return f"mcp_get_prompt → prompt {args.get('name','?')} from {args.get('server','?')}"
    if name in ("mcp_list_resources", "mcp_list_prompts"):
        return name
    if name == "spawn_agent":
        role = args.get("role") or "agent"
        task = (args.get("task") or "?")[:60]
        return f"spawn_agent → {role}: {task}"
    if name == "spawn_agents":
        raw = args.get("tasks")
        tasks = raw if isinstance(raw, list) else []
        summary = "; ".join(
            (t.get("task", "?") if isinstance(t, dict) else str(t))[:30]
            for t in tasks[:3]
        )
        extra = "" if len(tasks) <= 3 else f" (+{len(tasks) - 3} more)"
        return f"spawn_agents → {len(tasks)} agents: {summary}{extra}"
    if name == "remember":
        return f"remember → {args.get('name', '?')} ({args.get('type', '?')})"
    if name == "update_memory":
        return f"update_memory → {args.get('name', '?')}"
    if name == "forget":
        return f"forget → {args.get('name', '?')}"
    if name == "read_memory":
        return f"read_memory → {args.get('name', '?')}"
    if name.startswith(MCP_PREFIX):
        # name is mcp__<server>__<tool>; recover a readable server.tool(args)
        body = name[len(MCP_PREFIX):]
        server, _, tool = body.partition("__")
        return f"{name} → {server}.{tool}({args})"
    return f"{name} {args}"
