"""OpenAI-compatible chat client with native tool-call support.

One client speaks /v1/chat/completions, which every local runner (Ollama,
LM Studio, llama.cpp, vLLM) and OpenAI and OpenRouter expose. Non-OpenAI-shaped
providers (Anthropic direct, Codex OAuth) attach later behind the same chat()
signature.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Profile


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string exactly as the model returned it


@dataclass
class ChatResult:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def wants_tool(self) -> bool:
        return bool(self.tool_calls)


class LLMClient:
    def __init__(self, profile: Profile, *, client: httpx.Client | None = None) -> None:
        self.profile = profile
        self._client = client or httpx.Client(timeout=profile.timeout)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.profile.api_key:
            headers["Authorization"] = f"Bearer {self.profile.api_key}"
        return headers

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
        resp = self._client.post(
            f"{self.profile.base_url}/chat/completions",
            json=payload,
            headers=self._headers(),
        )
        resp.raise_for_status()
        message = resp.json()["choices"][0]["message"]
        return _parse_message(message)


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
