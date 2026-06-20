import pytest

from heya.agent import Agent
from heya.llm_client import ChatResult, ToolCall


class FakeClient:
    """Returns scripted ChatResults; records messages it was called with."""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []
        self.last_tools = None  # captures the `tools` list passed to chat_stream

    def chat_stream(self, messages, tools=None, on_text=None):
        self.calls.append([dict(m) for m in messages])
        self.last_tools = tools
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


from heya.agent import SELF_REVIEW_NUDGE


def test_self_review_runs_after_a_write(tmp_path):
    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="write_file",
            arguments=f'{{"path": "{tmp_path / "out.txt"}", "content": "x"}}')]),
        ChatResult(content="done writing"),
        ChatResult(content="reviewed, all good"),
    ]
    client = FakeClient(scripted)
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(), self_review=True)
    answer = agent.run("write out.txt")
    assert answer == "reviewed, all good"
    assert any(
        m["role"] == "user" and m["content"] == SELF_REVIEW_NUDGE
        for m in client.calls[-1]
    )


def test_self_review_skipped_when_nothing_changed(tmp_path):
    client = FakeClient([ChatResult(content="just an answer")])
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(), self_review=True)
    answer = agent.run("what is 2+2?")
    assert answer == "just an answer"
    assert len(client.calls) == 1  # no extra review turn


def test_self_review_skipped_when_disabled(tmp_path):
    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="write_file",
            arguments=f'{{"path": "{tmp_path / "out.txt"}", "content": "x"}}')]),
        ChatResult(content="done writing"),
    ]
    client = FakeClient(scripted)
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(), self_review=False)
    answer = agent.run("write out.txt")
    assert answer == "done writing"
    assert len(client.calls) == 2  # no review turn


def test_assistant_message_carries_wire_valid_tool_calls(tmp_path):
    # Lock the OpenAI message envelope: an assistant turn with tool calls must
    # serialize as {"type": "function", "function": {name, arguments}} so the
    # following tool-result messages are accepted by the API.
    (tmp_path / "a.txt").write_text("x")
    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="call_7", name="read_file",
            arguments=f'{{"path": "{tmp_path / "a.txt"}"}}')]),
        ChatResult(content="done"),
    ]
    agent, _ = make_agent(tmp_path, scripted)
    agent.run("read it")
    assistant = next(
        m for m in agent.messages if m["role"] == "assistant" and m.get("tool_calls")
    )
    call = assistant["tool_calls"][0]
    assert call["id"] == "call_7"
    assert call["type"] == "function"
    assert call["function"]["name"] == "read_file"
    assert "path" in call["function"]["arguments"]
    # The matching tool result references the same id.
    tool_msg = next(m for m in agent.messages if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call_7"


def test_agent_threads_guidance_sources(tmp_path):
    skill = tmp_path / "voice"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: voice\ndescription: d\n---\nGROUNDING TEXT\n")
    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="read_guidance",
            arguments='{"name": "voice"}')]),
        ChatResult(content="grounded answer"),
    ]
    client = FakeClient(scripted)
    agent = Agent(
        client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
        self_review=False, guidance_sources=[tmp_path],
    )
    answer = agent.run("use the voice guidance")
    assert answer == "grounded answer"
    assert any(
        m["role"] == "tool" and "GROUNDING TEXT" in m["content"] for m in client.calls[1]
    )


def test_agent_threads_search_provider(tmp_path):
    from heya.tools_web import SearchResult

    class Provider:
        def search(self, query, max_results=5):
            return [SearchResult(title="R", url="https://r", snippet="snip")]

    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="web_search",
            arguments='{"query": "heya"}')]),
        ChatResult(content="searched"),
    ]
    client = FakeClient(scripted)
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False, search_provider=Provider())
    answer = agent.run("search for heya")
    assert answer == "searched"
    assert any(m["role"] == "tool" and "https://r" in m["content"] for m in client.calls[1])


def test_agent_threads_browser_session(tmp_path):
    class Session:
        def navigate(self, url):
            return f"navigated {url}"
        def close(self):
            self.closed = True

    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="browser_navigate",
            arguments='{"url": "https://x"}')]),
        ChatResult(content="done"),
    ]
    client = FakeClient(scripted)
    session = Session()
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False, browser_session=session)
    answer = agent.run("open x")
    assert answer == "done"
    assert any(m["role"] == "tool" and "navigated https://x" in m["content"] for m in client.calls[1])


def test_agent_close_closes_browser(tmp_path):
    class Session:
        closed = False
        def close(self):
            self.closed = True

    session = Session()
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), browser_session=session)
    agent.close()
    assert session.closed is True


def test_agent_threads_process_registry(tmp_path, monkeypatch):
    import heya.agent as agent_mod

    captured = {}

    def fake_dispatch(name, arguments, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(agent_mod, "dispatch_tool", fake_dispatch)
    agent = Agent(
        FakeClient([ChatResult(content=None, tool_calls=[
            ToolCall(id="1", name="check_command", arguments='{"id": "p1"}')
        ]), ChatResult(content="done")]),
        allowed_roots=[tmp_path],
        cwd=tmp_path,
        approval=_AllowAll(),
        self_review=False,
        process_registry="REG",
    )
    agent.run("check p1")
    assert captured.get("process_registry") == "REG"


def test_agent_close_closes_registry(tmp_path):
    class Registry:
        closed = False
        def close(self):
            self.closed = True

    reg = Registry()
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), process_registry=reg)
    agent.close()
    assert reg.closed is True


class FakeMCPRuntime:
    def __init__(self):
        self.closed = False
        self.calls = []

    def list_tools(self):
        return [("demo", {"name": "ping", "description": "p", "inputSchema": {"type": "object"}})]

    def has_resources(self):
        return False

    def has_prompts(self):
        return False

    def call_tool(self, server, tool, arguments, *, timeout=120.0):
        self.calls.append((server, tool, arguments))
        return "PONG"

    def close(self):
        self.closed = True


def test_agent_sends_mcp_tools_to_model(tmp_path):
    rt = FakeMCPRuntime()
    # make_agent passes **kw through to Agent, so mcp_runtime is accepted
    agent, client = make_agent(tmp_path, [ChatResult(content="done")], mcp_runtime=rt)
    agent.run("hi")
    assert client.last_tools is not None
    assert any(t["function"]["name"] == "mcp__demo__ping" for t in client.last_tools)


def test_agent_close_tears_down_runtime(tmp_path):
    rt = FakeMCPRuntime()
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), mcp_runtime=rt)
    agent.close()
    assert rt.closed is True
