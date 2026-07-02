"""OpenAI-compatible chat client with native tool-call support.

One client speaks /v1/chat/completions, which every local runner (Ollama,
LM Studio, llama.cpp, vLLM) and OpenAI and OpenRouter expose. Non-OpenAI-shaped
providers (Anthropic direct, Codex OAuth) attach later behind the same chat()
signature.
"""
from __future__ import annotations

import json
import time

from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from .config import Profile
from .text import estimate_messages_tokens, estimate_tokens


_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string exactly as the model returned it


@dataclass
class Usage:
    prompt_tokens: int
    completion_tokens: int
    estimated: bool = False

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class ChatResult:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: "Usage | None" = None

    @property
    def wants_tool(self) -> bool:
        return bool(self.tool_calls)


class LLMClient:
    def __init__(self, profile: Profile, *, client: httpx.Client | None = None,
                 api_key: str | None = None, max_retries: int = 3,
                 backoff_base: float = 0.5,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.profile = profile
        self._client = client or httpx.Client(timeout=profile.timeout)
        self._api_key_override = api_key
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._sleep = sleep

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = self._api_key_override or self.profile.api_key
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _retry_delay(self, attempt: int, exc: Exception) -> float:
        if isinstance(exc, httpx.HTTPStatusError):
            ra = exc.response.headers.get("Retry-After")
            if ra:
                try:
                    return float(int(ra))
                except ValueError:
                    pass
        return self._backoff_base * (2 ** attempt)

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in _RETRYABLE_STATUS
        return False

    def _with_retry(self, fn: Callable[[], Any]) -> Any:
        attempt = 0
        while True:
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 - re-raised below unless transient
                if attempt >= self._max_retries or not self._is_transient(exc):
                    raise
                self._sleep(self._retry_delay(attempt, exc))
                attempt += 1

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.profile.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        def _do() -> dict[str, Any]:
            resp = self._client.post(
                f"{self.profile.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

        body = self._with_retry(_do)
        message = body["choices"][0]["message"]
        result = _parse_message(message)
        u = body.get("usage")
        if u:
            result.usage = Usage(int(u.get("prompt_tokens") or 0),
                                 int(u.get("completion_tokens") or 0), estimated=False)
        return result

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.profile.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
        content_parts: list[str] = []
        acc: dict[int, dict[str, str]] = {}
        usage_raw = None

        def _open() -> tuple[Any, Any]:
            cm = self._client.stream(
                "POST",
                f"{self.profile.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            )
            resp = cm.__enter__()
            try:
                resp.raise_for_status()
            except Exception:
                cm.__exit__(None, None, None)
                raise
            return cm, resp

        cm, resp = self._with_retry(_open)
        try:
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if chunk.get("usage"):
                    usage_raw = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                text = delta.get("content")
                if text:
                    content_parts.append(text)
                    if on_text:
                        on_text(text)
                _accumulate_tool_calls(acc, delta.get("tool_calls") or [])
        finally:
            cm.__exit__(None, None, None)
        content = "".join(content_parts) or None
        tool_calls = [
            ToolCall(id=slot["id"], name=slot["name"], arguments=slot["arguments"])
            for _, slot in sorted(acc.items())
        ]
        if usage_raw:
            usage = Usage(int(usage_raw.get("prompt_tokens") or 0),
                          int(usage_raw.get("completion_tokens") or 0), estimated=False)
        else:
            usage = Usage(estimate_messages_tokens(messages),
                          estimate_tokens(content or ""), estimated=True)
        return ChatResult(content=content, tool_calls=tool_calls, usage=usage)


def _parse_message(message: dict[str, Any]) -> ChatResult:
    raw_calls = message.get("tool_calls") or []
    tool_calls = [
        ToolCall(
            id=c.get("id", ""),
            name=c["function"]["name"],
            arguments=c["function"].get("arguments", ""),
        )
        for c in raw_calls
    ]
    return ChatResult(content=message.get("content"), tool_calls=tool_calls)


def _accumulate_tool_calls(acc: dict[int, dict[str, str]], deltas: list[dict[str, Any]]) -> None:
    """Merge streamed tool-call fragments into acc, keyed by index."""
    for tc in deltas:
        idx = tc.get("index", 0)
        slot = acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
        if tc.get("id"):
            slot["id"] = tc["id"]
        fn = tc.get("function") or {}
        if fn.get("name"):
            slot["name"] = fn["name"]
        if fn.get("arguments"):
            slot["arguments"] += fn["arguments"]
