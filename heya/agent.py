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
from .tools import TOOL_SCHEMAS, describe_call, dispatch_tool

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
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
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
        """Release external resources (the browser session, if any)."""
        if self.browser_session is not None:
            self.browser_session.close()

    def _loop(self) -> str:
        for _ in range(self.max_iters):
            result = self.client.chat_stream(self.messages, tools=TOOL_SCHEMAS, on_text=self.on_text)
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
        if not self.approval.check(call.name, detail):
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
        )
        if call.name in ("write_file", "run_command") and not output.startswith("Error"):
            self._mutated = True
        return output
