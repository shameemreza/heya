import json

import httpx

from heya.config import Profile
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
