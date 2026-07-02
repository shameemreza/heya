import json
import httpx
import pytest
from heya.config import Profile
from heya.llm_client import LLMClient

def _profile():
    return Profile(name="t", base_url="http://x/v1", model="m", timeout=5.0)

def test_chat_retries_transient_500_then_succeeds():
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    slept = []
    llm = LLMClient(_profile(), client=client, sleep=slept.append)
    result = llm.chat([{"role": "user", "content": "hi"}])
    assert result.content == "ok"
    assert calls["n"] == 2
    assert slept  # backed off once

def test_chat_gives_up_after_max_retries():
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        return httpx.Response(500)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    llm = LLMClient(_profile(), client=client, max_retries=2, sleep=lambda s: None)
    with pytest.raises(httpx.HTTPStatusError):
        llm.chat([{"role": "user", "content": "hi"}])
    assert calls["n"] == 3  # initial try + 2 retries

def test_chat_does_not_retry_400():
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        return httpx.Response(400)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    llm = LLMClient(_profile(), client=client, sleep=lambda s: None)
    with pytest.raises(httpx.HTTPStatusError):
        llm.chat([{"role": "user", "content": "hi"}])
    assert calls["n"] == 1

def test_chat_honors_retry_after():
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    slept = []
    llm = LLMClient(_profile(), client=client, sleep=slept.append)
    llm.chat([{"role": "user", "content": "hi"}])
    assert slept == [7.0]

def test_stream_skips_malformed_chunk():
    good = {"choices": [{"delta": {"content": "hello"}}]}
    def handler(request):
        body = "data: not-json\n\n" + f"data: {json.dumps(good)}\n\n" + "data: [DONE]\n\n"
        return httpx.Response(200, text=body)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    llm = LLMClient(_profile(), client=client, sleep=lambda s: None)
    result = llm.chat_stream([{"role": "user", "content": "hi"}])
    assert result.content == "hello"

def test_stream_retries_transient_503_then_succeeds():
    good = {"choices": [{"delta": {"content": "hello"}}]}
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        body = f"data: {json.dumps(good)}\n\n" + "data: [DONE]\n\n"
        return httpx.Response(200, text=body)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    slept = []
    llm = LLMClient(_profile(), client=client, sleep=slept.append)
    result = llm.chat_stream([{"role": "user", "content": "hi"}])
    assert result.content == "hello"
    assert calls["n"] == 2
    assert slept  # backed off once
