import asyncio

from mcp.types import (
    CreateMessageRequestParams, CreateMessageResult, SamplingMessage, TextContent, ErrorData,
)
from heya.mcp_callbacks import sampling_messages_to_llm, build_sampling_callback


class FakeChatResult:
    def __init__(self, content):
        self.content = content


class FakeProfile:
    model = "fake-model"


class FakeLLM:
    def __init__(self, content="sampled-answer", raises=False):
        self._content = content
        self._raises = raises
        self.profile = FakeProfile()
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append(messages)
        if self._raises:
            raise RuntimeError("llm down")
        return FakeChatResult(self._content)


def _params(system="be brief", text="hello"):
    return CreateMessageRequestParams(
        messages=[SamplingMessage(role="user", content=TextContent(type="text", text=text))],
        systemPrompt=system, maxTokens=100,
    )


def test_sampling_messages_to_llm_prepends_system():
    msgs = sampling_messages_to_llm(_params(system="sys", text="hi"))
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[1] == {"role": "user", "content": "hi"}


def test_sampling_declined_returns_error_no_llm_call():
    llm = FakeLLM()
    cb = build_sampling_callback(llm, lambda s, p: False, "srv")
    result = asyncio.run(cb(None, _params()))
    assert isinstance(result, ErrorData)
    assert llm.calls == []  # never ran the model


def test_sampling_approved_runs_llm_and_returns_result():
    llm = FakeLLM(content="the answer")
    cb = build_sampling_callback(llm, lambda s, p: True, "srv")
    result = asyncio.run(cb(None, _params()))
    assert isinstance(result, CreateMessageResult)
    assert result.content.text == "the answer"
    assert result.model == "fake-model"
    assert llm.calls and llm.calls[0][0]["role"] == "system"


def test_sampling_llm_error_returns_error_data():
    llm = FakeLLM(raises=True)
    cb = build_sampling_callback(llm, lambda s, p: True, "srv")
    result = asyncio.run(cb(None, _params()))
    assert isinstance(result, ErrorData)
