"""The ReAct agent loop: stream a reply, run approved tools, repeat.

One Agent instance holds the conversation, so interactive turns accumulate
context. Gated tools route through an ApprovalPolicy; results (including refusals
and errors) are always fed back so the model can recover. After a task that
changed something, one scoped self-review pass runs.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .approval import ApprovalPolicy
from .subagents import LabeledStream, build_child_system_prompt, resolve_role, ROLES
from .tools import build_tool_schemas, describe_call, dispatch_tool

SYSTEM_PROMPT = (
    "You are Heya, a careful, capable command-line assistant. You help with "
    "engineering, support, research, writing, and analysis. You can read and write "
    "files and run shell commands, but only inside the folders you are allowed to "
    "use. Prefer reading before writing. Use tools to get real answers rather than "
    "guessing. Keep replies clear and direct, in natural human prose. When a task is "
    "done, give a short, plain final answer."
    " When a task involves writing, code review, debugging, or following standards, call read_guidance first to consult relevant internal guidance and follow it — it is the source of truth for standards and voice."
    " You can search the web (web_search) and read pages (web_fetch) when a task needs current or external information; note that these send the query or URL to a third party."
    " You can drive a real browser to reproduce issues: browser_navigate, browser_snapshot, browser_click, browser_type, browser_screenshot, and browser_evidence (console and network errors). Take a snapshot after each action to see the result."
    " For WordPress work you can tail a site's error log (read_log), run WP-CLI (run_wp_cli), and boot a disposable clean WordPress to reproduce on (wp_playground). Each takes the site's root directory as `path`; if you cannot tell which site is meant, ask the user rather than guessing. Use dev/staging sites only, never production, and back up before destructive WP-CLI ops (db reset, site empty)."
    " For long-lived commands (a dev server, a watcher), run_command with background=true returns a process id; read its output with check_command and stop it with kill_command."
    " You may also have MCP tools from servers the user configured (names like mcp__<server>__<tool>); these reach external systems and are approval-gated, and the user controls which servers are connected."
)

SELF_REVIEW_NUDGE = (
    "Before finalizing: review what you just did against my original request. If "
    "anything is wrong, incomplete, or unsafe, fix it now with tools. If it is "
    "correct, reply with your final answer."
)

DEFAULT_MAX_ITERS = 12
DEFAULT_COMMAND_TIMEOUT = 120.0


class Agent:
    def __init__(
        self,
        client: Any,
        *,
        allowed_roots,
        cwd: Path,
        approval: ApprovalPolicy | None = None,
        on_text: Callable[[str], None] | None = None,
        self_review: bool = True,
        max_iters: int = DEFAULT_MAX_ITERS,
        command_timeout: float = DEFAULT_COMMAND_TIMEOUT,
        guidance_sources: Sequence[Path] = (),
        search_provider=None,
        browser_session=None,
        process_registry=None,
        wp_default_root=None,
        playground_session=None,
        mcp_runtime=None,
        label: str = "",
        spawn_depth: int = 0,
        max_spawn_depth: int = 1,
        max_children: int = 4,
        tool_filter: frozenset[str] | None = None,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self.client = client
        self.allowed_roots = list(allowed_roots)
        self.cwd = Path(cwd)
        self.approval = approval or ApprovalPolicy()
        self.on_text = on_text
        self.self_review = self_review
        self.max_iters = max_iters
        self.command_timeout = command_timeout
        self.guidance_sources = list(guidance_sources)
        self.search_provider = search_provider
        self.browser_session = browser_session
        self.process_registry = process_registry
        self.wp_default_root = wp_default_root
        self.playground_session = playground_session
        self.mcp_runtime = mcp_runtime
        self.label = label
        self.spawn_depth = spawn_depth
        self.max_spawn_depth = max_spawn_depth
        self.max_children = max_children
        self.tool_filter = tool_filter
        self._root_on_text = on_text
        self._children_spawned = 0
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        self._mutated = False

    def run(self, user_message: str) -> str:
        """Run one task to a final answer, with optional scoped self-review."""
        self.messages.append({"role": "user", "content": user_message})
        self._mutated = False
        answer = self._loop()
        if self.self_review and self._mutated:
            self.messages.append({"role": "user", "content": SELF_REVIEW_NUDGE})
            self._mutated = False
            answer = self._loop()
        return answer

    def close(self) -> None:
        """Release external resources: browser session, background processes,
        the WordPress Playground session, and the MCP runtime."""
        if self.browser_session is not None:
            self.browser_session.close()
        if self.process_registry is not None:
            self.process_registry.close()
        if self.playground_session is not None:
            self.playground_session.close()
        if self.mcp_runtime is not None:
            self.mcp_runtime.close()

    def _loop(self) -> str:
        can_spawn = self.spawn_depth < self.max_spawn_depth
        tools = build_tool_schemas(self.mcp_runtime, can_spawn=can_spawn)
        if self.tool_filter is not None:
            tools = [t for t in tools if t["function"]["name"] in self.tool_filter]
        for _ in range(self.max_iters):
            result = self.client.chat_stream(self.messages, tools=tools, on_text=self.on_text)
            self.messages.append(self._assistant_message(result))
            if not result.tool_calls:
                return result.content or ""
            for call in result.tool_calls:
                output = self._handle_call(call)
                self.messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": output}
                )
        return "Stopped: reached max iterations without a final answer."

    def _assistant_message(self, result) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": result.content or ""}
        if result.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in result.tool_calls
            ]
        return message

    def _handle_call(self, call) -> str:
        detail = describe_call(call.name, call.arguments)
        if self.tool_filter is not None and call.name not in self.tool_filter:
            return f"Error: tool {call.name!r} is not available to the {self.label} sub-agent."
        if not self.approval.check(call.name, detail, label=self.label):
            return f"Declined by user: {detail}"
        output = dispatch_tool(
            call.name,
            call.arguments,
            allowed_roots=self.allowed_roots,
            cwd=self.cwd,
            timeout=self.command_timeout,
            guidance_sources=self.guidance_sources,
            search_provider=self.search_provider,
            browser_session=self.browser_session,
            process_registry=self.process_registry,
            wp_default_root=self.wp_default_root,
            playground_session=self.playground_session,
            mcp_runtime=self.mcp_runtime,
            spawn_fn=self._spawn_agent,
        )
        mutating = call.name in ("write_file", "run_command", "run_wp_cli")
        if mutating and not output.startswith(("Error", "Started background process", "Declined")):
            self._mutated = True
        return output

    def _make_child(self, role, instructions) -> "Agent":
        """Build a fresh child Agent: isolated context, shared resources."""
        label = role.name if role is not None else "agent"
        if self._root_on_text is not None:
            stream = LabeledStream(self._root_on_text, label)
            child_on_text = stream.write
        else:
            child_on_text = None
        return Agent(
            self.client,
            allowed_roots=self.allowed_roots,
            cwd=self.cwd,
            approval=self.approval,
            on_text=child_on_text,
            self_review=False,
            max_iters=self.max_iters,
            command_timeout=self.command_timeout,
            guidance_sources=self.guidance_sources,
            search_provider=self.search_provider,
            browser_session=self.browser_session,
            process_registry=self.process_registry,
            wp_default_root=self.wp_default_root,
            playground_session=self.playground_session,
            mcp_runtime=self.mcp_runtime,
            label=label,
            spawn_depth=self.spawn_depth + 1,
            max_spawn_depth=self.max_spawn_depth,
            max_children=self.max_children,
            tool_filter=role.tools if role is not None else None,
            system_prompt=build_child_system_prompt(SYSTEM_PROMPT, role, instructions),
        )

    def _spawn_agent(self, task, role=None, instructions=None) -> str:
        """Run a child agent to completion and return its final report."""
        if self._children_spawned >= self.max_children:
            return "Error: sub-agent limit reached for this task."
        if role is not None and resolve_role(role) is None:
            return f"Error: unknown role {role!r}. Available: {sorted(ROLES)}."
        self._children_spawned += 1
        resolved = resolve_role(role)
        child = self._make_child(resolved, instructions)
        try:
            return child.run(task)
        except Exception as exc:  # never raise into dispatch
            return f"Error: sub-agent failed: {exc}"
