import asyncio

import pytest

pytest.importorskip("mcp")  # the MCP SDK is an optional extra (heya-agent[mcp])

from mcp.types import (
    CreateMessageRequestParams, CreateMessageResult, SamplingMessage, TextContent, ErrorData,
    ElicitResult, ElicitRequestFormParams, ElicitRequestURLParams, LoggingMessageNotificationParams,
)
from heya.mcp_callbacks import (
    sampling_messages_to_llm, build_sampling_callback,
    coerce_value, build_elicitation_callback, build_logging_callback,
)


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


class FakePrompter:
    def __init__(self, form_answer=None, url_ok=True):
        self._form = form_answer
        self._url = url_ok
        self.calls = []

    def form(self, server, message, schema):
        self.calls.append(("form", message))
        return self._form

    def url(self, server, message, url):
        self.calls.append(("url", url))
        return self._url


def test_coerce_value_types():
    assert coerce_value("5", {"type": "integer"}) == 5
    assert coerce_value("2.5", {"type": "number"}) == 2.5
    assert coerce_value("true", {"type": "boolean"}) is True
    assert coerce_value("no", {"type": "boolean"}) is False
    assert coerce_value("hi", {"type": "string"}) == "hi"
    assert coerce_value("x", {"type": "array"}) == "x"  # unknown -> raw
    assert coerce_value("abc", {"type": "integer"}) == "abc"  # bad int -> raw


def _form_params():
    return ElicitRequestFormParams(
        mode="form", message="Pick", requestedSchema={"type": "object", "properties": {"n": {"type": "integer"}}},
    )


def _url_params():
    return ElicitRequestURLParams(mode="url", message="Visit", url="https://x/auth", elicitationId="e1")


def test_elicit_form_accept():
    cb = build_elicitation_callback(FakePrompter(form_answer={"n": 3}), "srv")
    r = asyncio.run(cb(None, _form_params()))
    assert r.action == "accept" and r.content == {"n": 3}


def test_elicit_form_decline():
    cb = build_elicitation_callback(FakePrompter(form_answer=None), "srv")
    r = asyncio.run(cb(None, _form_params()))
    assert r.action == "decline"


def test_elicit_url_accept_and_decline():
    assert asyncio.run(build_elicitation_callback(FakePrompter(url_ok=True), "s")(None, _url_params())).action == "accept"
    assert asyncio.run(build_elicitation_callback(FakePrompter(url_ok=False), "s")(None, _url_params())).action == "decline"


def test_logging_callback_formats_text_and_dict():
    lines = []
    cb = build_logging_callback("srv", lines.append)
    asyncio.run(cb(LoggingMessageNotificationParams(level="info", data="hello")))
    asyncio.run(cb(LoggingMessageNotificationParams(level="error", data={"k": 1})))
    assert lines[0] == "[srv] info: hello"
    assert "error" in lines[1] and '"k"' in lines[1] and "srv" in lines[1]


def test_logging_callback_non_serializable_data_does_not_crash():
    class Weird:
        def __repr__(self):
            return "<weird>"

    lines = []
    cb = build_logging_callback("srv", lines.append)
    asyncio.run(cb(LoggingMessageNotificationParams(level="warning", data=Weird())))
    assert lines == ["[srv] warning: <weird>"]
