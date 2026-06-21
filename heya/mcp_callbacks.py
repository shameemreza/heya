"""Heya's MCP server->client callbacks: sampling, elicitation, logging.

The SDK's ClientSession invokes these when a server asks the client to run an
LLM completion (sampling), prompt the user (elicitation), or display a log line
(logging). Each runs on the runtime loop-thread; blocking work (the sync LLM
client, stdin prompts) is offloaded with run_in_executor so the loop never
blocks. All SDK type names stay in this module and the runtime opener.
"""
from __future__ import annotations

import asyncio
import json as _json
from dataclasses import dataclass

_MAX_PREVIEW = 500


def _text_of(content) -> str:
    text = getattr(content, "text", None)
    return text if text is not None else "[non-text content]"


def sampling_messages_to_llm(params) -> list[dict]:
    """Convert an MCP sampling request to LLM chat messages (system prepended)."""
    messages: list[dict] = []
    system = getattr(params, "systemPrompt", None)
    if system:
        messages.append({"role": "system", "content": system})
    for m in params.messages:
        messages.append({"role": m.role, "content": _text_of(m.content)})
    return messages


def _sampling_preview(server: str, params) -> str:
    system = (getattr(params, "systemPrompt", None) or "")[:200]
    first = _text_of(params.messages[0].content)[:200] if params.messages else ""
    prefs = getattr(params, "modelPreferences", None)
    hint = f" | modelPreferences: {prefs}" if prefs else ""
    return (f"{server} requests an LLM completion. system: {system!r} | "
            f"first message: {first!r} | maxTokens: {getattr(params, 'maxTokens', None)}{hint}")[:_MAX_PREVIEW]


def coerce_value(raw: str, prop_schema: dict):
    t = (prop_schema or {}).get("type")
    try:
        if t == "integer":
            return int(raw)
        if t == "number":
            return float(raw)
        if t == "boolean":
            return raw.strip().lower() in ("1", "true", "yes", "y")
    except (TypeError, ValueError):
        return raw
    return raw  # string / enum / unsupported -> raw text


def build_elicitation_callback(prompter, server_name):
    from mcp.types import ElicitResult, ElicitRequestURLParams

    async def _callback(context, params):
        loop = asyncio.get_running_loop()
        if isinstance(params, ElicitRequestURLParams):
            ok = await loop.run_in_executor(None, prompter.url, server_name, params.message, str(params.url))
            return ElicitResult(action="accept" if ok else "decline")
        schema = getattr(params, "requestedSchema", None) or {}
        answers = await loop.run_in_executor(None, prompter.form, server_name, params.message, schema)
        if answers is None:
            return ElicitResult(action="decline")
        return ElicitResult(action="accept", content=answers)

    return _callback


def build_logging_callback(server_name, sink):
    async def _callback(params):
        data = params.data
        if isinstance(data, str):
            text = data
        else:
            try:
                text = _json.dumps(data, separators=(",", ":"))
            except (TypeError, ValueError):  # data is Any; never raise into the SDK
                text = repr(data)
        sink(f"[{server_name}] {params.level}: {text[:_MAX_PREVIEW]}")

    return _callback


class StdinElicitPrompter:
    """Default elicitation prompter over the terminal."""

    def form(self, server, message, schema):
        print(f"[{server}] {message}")
        answers = {}
        for name, prop in (schema.get("properties") or {}).items():
            raw = input(f"  {name} ({prop.get('type', 'string')}; blank to decline): ").strip()
            if raw == "":
                return None
            answers[name] = coerce_value(raw, prop)
        return answers

    def url(self, server, message, url):
        print(f"[{server}] {message}\n  Visit: {url}")
        return input("  Done? [y/N]: ").strip().lower() in ("y", "yes")


def stdin_sampling_approver(server: str, preview: str) -> bool:
    print(f"[{server}] {preview}")
    return input("Allow this sampling request? [y/N]: ").strip().lower() in ("y", "yes")


@dataclass
class CallbackDeps:
    sampling_approver: object
    elicit_prompter: object
    log_sink: object
    llm_client: object | None = None


def build_sampling_callback(llm_client, approver, server_name, *, on_note=None):
    from mcp.types import CreateMessageResult, TextContent, ErrorData

    async def _callback(context, params):
        loop = asyncio.get_running_loop()
        preview = _sampling_preview(server_name, params)
        approved = await loop.run_in_executor(None, approver, server_name, preview)
        if not approved:
            return ErrorData(code=-32001, message="sampling declined by user")
        messages = sampling_messages_to_llm(params)
        try:
            result = await loop.run_in_executor(None, lambda: llm_client.chat(messages))
        except Exception as exc:  # never raise into the SDK
            return ErrorData(code=-32000, message=f"sampling failed: {exc}")
        if on_note is not None:
            on_note(f"ran sampling for {server_name}")
        return CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text=result.content or ""),
            model=getattr(llm_client.profile, "model", "unknown"),
            stopReason="endTurn",
        )

    return _callback
