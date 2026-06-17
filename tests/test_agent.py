import pytest

from heya.agent import Agent
from heya.llm_client import ChatResult, ToolCall


class FakeClient:
    """Returns scripted ChatResults; records messages it was called with."""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    def chat_stream(self, messages, tools=None, on_text=None):
        self.calls.append([dict(m) for m in messages])
        result = self._scripted.pop(0)
        if result.content and on_text:
            on_text(result.content)
        return result


class _AllowAll:
    def check(self, name, detail):
        return True


class _DenyGated:
    def check(self, name, detail):
        return name not in ("write_file", "run_command")


def make_agent(tmp_path, scripted, **kw):
    client = FakeClient(scripted)
    agent = Agent(
        client,
        allowed_roots=[tmp_path],
        cwd=tmp_path,
        approval=_AllowAll(),
        self_review=False,
        **kw,
    )
    return agent, client


def test_returns_plain_answer_without_tools(tmp_path):
    agent, _ = make_agent(tmp_path, [ChatResult(content="hello")])
    assert agent.run("hi") == "hello"


def test_runs_a_tool_then_returns_answer(tmp_path):
    (tmp_path / "a.txt").write_text("file body")
    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="read_file",
            arguments=f'{{"path": "{tmp_path / "a.txt"}"}}')]),
        ChatResult(content="the file says file body"),
    ]
    agent, client = make_agent(tmp_path, scripted)
    answer = agent.run("read a.txt")
    assert answer == "the file says file body"
    second_call = client.calls[1]
    assert any(m["role"] == "tool" and "file body" in m["content"] for m in second_call)


def test_declined_tool_feeds_refusal_back(tmp_path):
    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="write_file",
            arguments='{"path": "out.txt", "content": "x"}')]),
        ChatResult(content="ok, I won't"),
    ]
    client = FakeClient(scripted)
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_DenyGated(), self_review=False)
    answer = agent.run("write out.txt")
    assert answer == "ok, I won't"
    assert not (tmp_path / "out.txt").exists()
    assert any(m["role"] == "tool" and "Declined" in m["content"] for m in client.calls[1])


def test_stops_at_max_iters(tmp_path):
    looping = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="read_file", arguments='{"path": "x"}')])
        for _ in range(10)
    ]
    agent, _ = make_agent(tmp_path, looping, max_iters=3)
    answer = agent.run("loop forever")
    assert "max iterations" in answer.lower()


def test_conversation_memory_persists_across_turns(tmp_path):
    agent, client = make_agent(tmp_path, [ChatResult(content="first"), ChatResult(content="second")])
    agent.run("one")
    agent.run("two")
    second_turn_messages = client.calls[1]
    assert any(m["role"] == "user" and m["content"] == "one" for m in second_turn_messages)
    assert any(m["role"] == "assistant" and m["content"] == "first" for m in second_turn_messages)
