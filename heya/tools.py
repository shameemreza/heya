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

from .tools_files import ToolError, read_file, run_command, write_file

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
]


def dispatch_tool(
    name: str,
    arguments: str,
    *,
    allowed_roots: Sequence[Path],
    cwd: Path,
    timeout: float,
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
            return read_file(args["path"], allowed_roots=allowed_roots)
        if name == "write_file":
            n = write_file(args["path"], args["content"], allowed_roots=allowed_roots)
            return f"Wrote {n} bytes to {args['path']}."
        if name == "run_command":
            result = run_command(args["cmd"], cwd=cwd, allowed_roots=allowed_roots, timeout=timeout)
            return (
                f"exit_code: {result.exit_code}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
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
    return f"{name} {args}"
