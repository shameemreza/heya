import json

import httpx
import pytest

from heya.config import Profile, load_profiles, resolve_profile
from heya.llm_client import LLMClient


def _client(handler):
    profile = Profile(name="test", base_url="http://test/v1", model="m")
    transport = httpx.MockTransport(handler)
    return LLMClient(profile, client=httpx.Client(transport=transport))


def test_chat_posts_model_messages_and_no_stream():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "hi"}}]})

    _client(handler).chat([{"role": "user", "content": "hello"}])
    assert captured["url"] == "http://test/v1/chat/completions"
    assert captured["body"]["model"] == "m"
    assert captured["body"]["messages"][0]["content"] == "hello"
    assert captured["body"]["stream"] is False
    assert "tools" not in captured["body"]


def test_chat_parses_plain_text_reply():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "hi there"}}]})

    result = _client(handler).chat([{"role": "user", "content": "hello"}])
    assert result.content == "hi there"
    assert result.wants_tool is False
    assert result.tool_calls == []


def test_chat_sends_bearer_header_when_key_present(monkeypatch):
    monkeypatch.setenv("K", "abc")
    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    profile = Profile(name="t", base_url="http://test/v1", model="m", api_key_env="K")
    LLMClient(profile, client=httpx.Client(transport=httpx.MockTransport(handler))).chat(
        [{"role": "user", "content": "x"}]
    )
    assert captured["auth"] == "Bearer abc"


def test_chat_parses_tool_call_and_passes_tools_through():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "run_command",
                                        "arguments": '{"cmd":"ls /tmp"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": "Run a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {"cmd": {"type": "string"}},
                    "required": ["cmd"],
                },
            },
        }
    ]
    result = _client(handler).chat([{"role": "user", "content": "list /tmp"}], tools=tools)

    assert captured["body"]["tools"] == tools
    assert result.wants_tool is True
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.id == "call_1"
    assert call.name == "run_command"
    assert json.loads(call.arguments) == {"cmd": "ls /tmp"}


@pytest.mark.integration
def test_local_model_round_trips_a_tool_call():
    """Proof: the user-selected model returns a native tool call.

    Requires the 'local' profile's endpoint to be running with a tool-capable
    model. Run explicitly: .venv/bin/pytest -m integration
    """
    profile = resolve_profile("local", profiles=load_profiles())
    client = LLMClient(profile)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": "Run a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {"cmd": {"type": "string"}},
                    "required": ["cmd"],
                },
            },
        }
    ]
    result = client.chat(
        [{"role": "user", "content": "What files are in /tmp? Use the tool."}],
        tools=tools,
    )
    assert result.wants_tool, f"expected a tool call, got content: {result.content!r}"
    assert result.tool_calls[0].name == "run_command"
