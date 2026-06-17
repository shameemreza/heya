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

from .text import truncate_output
from .tools_files import ToolError, read_file, resolve_in_allowlist, run_command, write_file
from .tools_guidance import read_guidance as _read_guidance
from .tools_web import web_fetch, web_search

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
            "description": "Run a shell command in the working directory (inside the allowed folders). Returns stdout, stderr, and exit code.",
            "parameters": {
                "type": "object",
                "properties": {"cmd": {"type": "string", "description": "The shell command to run."}},
                "required": ["cmd"],
            },
        },
    },
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
) -> str:
    """Run one model tool-call. Returns a string result (errors included)."""
    try:
        args = json.loads(arguments) if arguments.strip() else {}
    except json.JSONDecodeError as exc:
        return f"Error: could not parse tool arguments as JSON: {exc}"
    if not isinstance(args, dict):
        return f"Error: tool arguments must be a JSON object, got {type(args).__name__}."
    try:
        if name == "read_file":
            return truncate_output(read_file(args["path"], allowed_roots=allowed_roots))
        if name == "write_file":
            n = write_file(args["path"], args["content"], allowed_roots=allowed_roots)
            return f"Wrote {n} bytes to {args['path']}."
        if name == "run_command":
            result = run_command(args["cmd"], cwd=cwd, allowed_roots=allowed_roots, timeout=timeout)
            return truncate_output(
                f"exit_code: {result.exit_code}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
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
        return f"run_command → {args.get('cmd', '?')}"
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
    return f"{name} {args}"
