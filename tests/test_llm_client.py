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


def _sse(*chunks: dict) -> bytes:
    import json as _json
    body = "".join(f"data: {_json.dumps(c)}\n\n" for c in chunks)
    body += "data: [DONE]\n\n"
    return body.encode()


def test_chat_stream_collects_text_and_calls_on_text():
    chunks = [
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=_sse(*chunks)))
    profile = Profile(name="t", base_url="http://test/v1", model="m")
    client = LLMClient(profile, client=httpx.Client(transport=transport))

    seen = []
    result = client.chat_stream([{"role": "user", "content": "hi"}], on_text=seen.append)

    assert result.content == "Hello"
    assert "".join(seen) == "Hello"
    assert result.wants_tool is False


def test_chat_stream_reassembles_split_tool_call():
    chunks = [
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "function": {"name": "read_file", "arguments": ""}}
        ]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"path":'}}
        ]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '"a.txt"}'}}
        ]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=_sse(*chunks)))
    profile = Profile(name="t", base_url="http://test/v1", model="m")
    client = LLMClient(profile, client=httpx.Client(transport=transport))

    result = client.chat_stream([{"role": "user", "content": "hi"}], tools=[{"x": 1}])

    assert result.wants_tool is True
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.id == "call_1"
    assert call.name == "read_file"
    assert call.arguments == '{"path":"a.txt"}'


@pytest.mark.integration
def test_local_model_streams_a_tool_call():
    """Proof: streaming + native tool-calls round-trip through the live model.

    Streaming reassembly is the highest-risk piece of the agent loop. Run
    explicitly: .venv/bin/python -m pytest -m integration
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
    streamed = []
    result = client.chat_stream(
        [{"role": "user", "content": "What files are in /tmp? Use the tool."}],
        tools=tools,
        on_text=streamed.append,
    )
    assert result.wants_tool, f"expected a tool call, got content: {result.content!r}"
    assert result.tool_calls[0].name == "run_command"
    # Arguments reassembled into valid JSON across deltas.
    json.loads(result.tool_calls[0].arguments)
