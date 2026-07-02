import threading

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
    def check(self, name, detail, label=""):
        return True


class _DenyGated:
    def check(self, name, detail, label=""):
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


def test_run_accepts_list_content(tmp_path):
    class CaptureClient:
        def __init__(self):
            self.profile = type("P", (), {"model": "m", "name": "local"})()
            self.seen = None

        def chat_stream(self, messages, tools=None, on_text=None):
            self.seen = [dict(m) for m in messages]
            return ChatResult(content="ok", tool_calls=[])

    client = CaptureClient()
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False)
    content = [{"type": "text", "text": "see this"},
               {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]
    agent.run(content)
    user_msgs = [m for m in client.seen if m.get("role") == "user"]
    assert user_msgs and user_msgs[-1]["content"] == content


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
                  self_review=False, browser_session=session, web_block_metadata=False)
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


from heya.agent import SYSTEM_PROMPT


def test_agent_uses_system_prompt_override(tmp_path):
    client = FakeClient([ChatResult(content="ok")])
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False, system_prompt="CUSTOM PROMPT")
    agent.run("hi")
    assert agent.messages[0] == {"role": "system", "content": "CUSTOM PROMPT"}


def test_handle_call_passes_label_to_approval(tmp_path):
    seen = {}
    class CaptureApproval:
        def check(self, name, detail, label=""):
            seen["label"] = label
            return True
    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="write_file",
            arguments=f'{{"path": "{tmp_path / "o.txt"}", "content": "x"}}')]),
        ChatResult(content="done"),
    ]
    agent = Agent(FakeClient(scripted), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=CaptureApproval(), self_review=False, label="reviewer")
    agent.run("write")
    assert seen["label"] == "reviewer"


def test_spawn_agent_runs_child_and_returns_report(tmp_path):
    # Parent turn: emit spawn_agent. Then parent turn: final answer.
    # The CHILD agent uses the SAME client instance (shared), so script the
    # child's reply after the parent's spawn call and before the parent's finish.
    scripted = [
        # parent: call spawn_agent
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="spawn_agent",
            arguments='{"task": "investigate", "role": "researcher"}')]),
        # child: its single final answer (no tools)
        ChatResult(content="child found the bug in auth.py"),
        # parent: final answer, now holding the child's report
        ChatResult(content="parent summary: bug is in auth.py"),
    ]
    client = FakeClient(scripted)
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False)
    answer = agent.run("delegate the investigation")
    assert answer == "parent summary: bug is in auth.py"
    # The parent's second turn carries the child's report as the tool result.
    assert any(
        m["role"] == "tool" and "child found the bug" in m["content"]
        for m in client.calls[-1]
    )


def test_child_context_is_isolated(tmp_path):
    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="spawn_agent",
            arguments='{"task": "do a thing"}')]),
        ChatResult(content="child done"),
        ChatResult(content="parent done"),
    ]
    client = FakeClient(scripted)
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False)
    agent.run("the parent's original instruction")
    # client.calls[1] is the child's first turn; it must NOT contain the parent's
    # user message, only the child's own system prompt + task.
    child_turn = client.calls[1]
    assert not any(
        m.get("content") == "the parent's original instruction" for m in child_turn
    )
    assert any(m["role"] == "user" and m["content"] == "do a thing" for m in child_turn)


def test_spawn_agent_fan_out_cap(tmp_path):
    # Directly exercise the cap via _spawn_agent with a stubbed _make_child.
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False, max_children=2)

    class _StubChild:
        def run(self, task):
            return "ok"
        def close(self):
            pass
    agent._make_child = lambda role, instructions, **kw: _StubChild()
    assert agent._spawn_agent("t1") == "ok"
    assert agent._spawn_agent("t2") == "ok"
    third = agent._spawn_agent("t3")
    assert "limit" in third.lower()


def test_spawn_agent_unknown_role_errors_without_spawning(tmp_path):
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False)
    called = {"made": False}
    def _make(role, instructions):
        called["made"] = True
    agent._make_child = _make
    out = agent._spawn_agent("task", role="bogus")
    assert "unknown role" in out.lower()
    assert called["made"] is False


def test_child_cannot_spawn_again_depth_cap(tmp_path):
    # A depth-1 child must not receive spawn_agent in its tool list.
    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="spawn_agent",
            arguments='{"task": "child task"}')]),
        ChatResult(content="child done"),   # child turn: capture its tools
        ChatResult(content="parent done"),
    ]
    client = FakeClient(scripted)
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False)
    agent.run("go")
    # last_tools reflects the most recent chat_stream call (parent's final turn).
    # Instead, assert via a child built directly:
    child = agent._make_child(None, None)
    assert child.spawn_depth == 1
    # Build the child's schema set the way its _loop would.
    from heya.tools import build_tool_schemas
    can_spawn = child.spawn_depth < child.max_spawn_depth
    names = {s["function"]["name"] for s in build_tool_schemas(can_spawn=can_spawn)}
    assert "spawn_agent" not in names


def test_spawned_child_shares_resources_and_is_not_closed(tmp_path):
    class Session:
        closed = False
        def navigate(self, url):
            return "ok"
        def close(self):
            self.closed = True
    session = Session()
    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="spawn_agent",
            arguments='{"task": "child task"}')]),
        ChatResult(content="child done"),
        ChatResult(content="parent done"),
    ]
    agent = Agent(FakeClient(scripted), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False, browser_session=session)
    agent.run("delegate")
    assert session.closed is False  # child must never close a shared session


def test_spawn_agent_flushes_child_on_exception(tmp_path):
    # If the child's run() raises, _spawn_agent must still (a) return a clean
    # error string (never-raise) and (b) call child.close() to flush its stream.
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False)

    class _BoomChild:
        def __init__(self):
            self.closed = False
        def run(self, task):
            raise RuntimeError("boom")
        def close(self):
            self.closed = True

    boom = _BoomChild()
    agent._make_child = lambda role, instructions, **kw: boom
    out = agent._spawn_agent("do it")
    assert out == "Error: sub-agent failed: boom"
    assert boom.closed is True  # flushed via finally even though run() raised


def test_children_budget_resets_each_task(tmp_path):
    # max_children is per-task: two successive run() calls that each spawn one
    # child must BOTH see the child's report (not a limit error), proving the
    # per-task budget resets. With max_children=1, no reset would block task two.
    turns = []
    for _ in range(2):
        turns += [
            ChatResult(content=None, tool_calls=[ToolCall(id="1", name="spawn_agent",
                arguments='{"task": "t"}')]),
            ChatResult(content="child done"),    # the child's turn
            ChatResult(content="parent done"),   # the parent's final turn
        ]
    client = FakeClient(turns)
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False, max_children=1)
    agent.run("task one")
    agent.run("task two")
    # client.calls = [t1-parent, t1-child, t1-parent-final,
    #                 t2-parent, t2-child, t2-parent-final]
    second_task_parent_final = client.calls[5]
    assert any(m["role"] == "tool" and "child done" in m["content"]
               for m in second_task_parent_final)
    assert not any(m["role"] == "tool" and "limit reached" in m["content"]
                   for m in second_task_parent_final)


from heya.subagents import PARALLEL_SAFE_TOOLS


def test_make_child_parallel_is_read_only_and_sessions_withheld(tmp_path):
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False,
                  browser_session="BROWSER", process_registry="REG",
                  playground_session="PG", on_text=lambda s: None)
    captured = []
    child = agent._make_child(None, None, parallel=True, index=1,
                              sink=captured.append)
    assert child.tool_filter == PARALLEL_SAFE_TOOLS
    assert child.browser_session is None
    assert child.process_registry is None
    assert child.playground_session is None
    assert child.label == "agent#1"


def test_make_child_parallel_role_intersects_filter(tmp_path):
    from heya.subagents import ROLES
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False, on_text=lambda s: None)
    child = agent._make_child(ROLES["reviewer"], None, parallel=True, index=2,
                              sink=lambda s: None)
    # reviewer's tools intersected with the parallel-safe surface
    assert child.tool_filter == (ROLES["reviewer"].tools & PARALLEL_SAFE_TOOLS)
    assert child.label == "reviewer#2"


def test_make_child_threads_original_root_on_text(tmp_path):
    # A child's _root_on_text must be the ORIGINAL root sink, not its own wrapped
    # LabeledStream — so a hypothetical grandchild wraps root, not the child.
    root_sink = lambda s: None
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False, on_text=root_sink)
    child = agent._make_child(None, None)  # non-parallel path
    assert child._root_on_text is root_sink


def test_make_child_nonparallel_still_shares_sessions(tmp_path):
    # 8a behavior preserved: a normal (non-parallel) child shares the sessions.
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False,
                  browser_session="BROWSER", process_registry="REG")
    child = agent._make_child(None, None)
    assert child.browser_session == "BROWSER"
    assert child.process_registry == "REG"


import time


class _FakeChild:
    def __init__(self, result=None, exc=None, delay=0.0):
        self._result, self._exc, self._delay = result, exc, delay
        self.closed = False

    def run(self, task):
        if self._delay:
            time.sleep(self._delay)
        if self._exc:
            raise self._exc
        return self._result if self._result is not None else f"report-{task}"

    def close(self):
        self.closed = True


def test_spawn_agents_returns_submission_order(tmp_path):
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False, max_children=5,
                  max_concurrent=5, on_text=lambda s: None)
    # children finish in reverse order; result must still be submission order
    seq = iter([
        _FakeChild(result="A", delay=0.03),
        _FakeChild(result="B", delay=0.01),
        _FakeChild(result="C", delay=0.0),
    ])
    agent._make_child = lambda role, instructions, **kw: next(seq)
    out = agent._spawn_agents([{"task": "t1"}, {"task": "t2"}, {"task": "t3"}])
    assert out.index("t1") < out.index("t2") < out.index("t3")
    assert "A" in out and "B" in out and "C" in out


def test_spawn_agents_isolates_failure(tmp_path):
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False, max_children=3,
                  max_concurrent=3, on_text=lambda s: None)
    seq = iter([
        _FakeChild(result="ok1"),
        _FakeChild(exc=RuntimeError("boom")),
        _FakeChild(result="ok3"),
    ])
    agent._make_child = lambda role, instructions, **kw: next(seq)
    out = agent._spawn_agents([{"task": "t1"}, {"task": "t2"}, {"task": "t3"}])
    assert "ok1" in out and "ok3" in out
    assert "(failed)" in out  # the middle child is a failed report, batch survived


def test_spawn_agents_times_out_slow_child(tmp_path):
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False, command_timeout=0.05,
                  max_children=2, max_concurrent=2, on_text=lambda s: None)
    agent._make_child = lambda role, instructions, **kw: _FakeChild(result="late", delay=0.5)
    out = agent._spawn_agents([{"task": "t1"}])
    assert "timed out" in out.lower()


def test_spawn_agents_respects_shared_budget(tmp_path):
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False, max_children=2,
                  max_concurrent=2, on_text=lambda s: None)
    agent._make_child = lambda role, instructions, **kw: _FakeChild()
    out = agent._spawn_agents([{"task": "t1"}, {"task": "t2"}, {"task": "t3"}])
    assert "t1" in out and "t2" in out
    assert "report-t3" not in out
    assert "not run" in out.lower()  # explicit dropped note
    assert agent._children_spawned == 2  # budget consumed


def test_spawn_agents_unknown_role_errors_without_spawning(tmp_path):
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False, on_text=lambda s: None)
    made = {"n": 0}
    def mk(*a, **k):
        made["n"] += 1
    agent._make_child = mk
    out = agent._spawn_agents([{"task": "t", "role": "bogus"}])
    assert "unknown role" in out.lower()
    assert made["n"] == 0


def test_spawn_agents_empty_errors(tmp_path):
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False)
    assert "non-empty" in agent._spawn_agents([]).lower()


def test_loop_passes_spawn_agents_fn(tmp_path, monkeypatch):
    import heya.agent as agent_mod
    captured = {}
    def fake_dispatch(name, arguments, **kwargs):
        captured.update(kwargs)
        return "ok"
    monkeypatch.setattr(agent_mod, "dispatch_tool", fake_dispatch)
    agent = Agent(
        FakeClient([
            ChatResult(content=None, tool_calls=[ToolCall(id="1", name="spawn_agents",
                arguments='{"tasks": [{"task": "t"}]}')]),
            ChatResult(content="done"),
        ]),
        allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(), self_review=False,
    )
    agent.run("go")
    assert captured.get("spawn_agents_fn") == agent._spawn_agents


def test_tool_filter_refuses_disallowed_tool(tmp_path):
    # A restricted agent that names a tool outside its filter gets a clean refusal
    # and the tool never runs.
    (tmp_path / "o.txt").write_text("orig")
    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="write_file",
            arguments=f'{{"path": "{tmp_path / "o.txt"}", "content": "HACKED"}}')]),
        ChatResult(content="gave up"),
    ]
    client = FakeClient(scripted)
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False, label="reviewer",
                  tool_filter=frozenset({"read_file"}))
    answer = agent.run("try to write")
    assert answer == "gave up"
    assert (tmp_path / "o.txt").read_text() == "orig"  # not written
    assert any(
        m["role"] == "tool" and "not available" in m["content"] for m in client.calls[1]
    )


def test_spawn_agents_isolates_make_child_failure(tmp_path):
    # A child whose CONSTRUCTION raises must be isolated to its own failed report;
    # siblings still complete (the batch is not aborted).
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False, max_children=3,
                  max_concurrent=3, on_text=lambda s: None)

    def mk(role, instructions, *, index=0, **kw):
        if index == 2:  # the second submitted child fails to build
            raise RuntimeError("construct boom")
        return _FakeChild(result=f"ok{index}")

    agent._make_child = mk
    out = agent._spawn_agents([{"task": "t1"}, {"task": "t2"}, {"task": "t3"}])
    assert "ok1" in out and "ok3" in out   # siblings survived
    assert "(failed)" in out               # the construction-failed child is marked failed


class _FakeMemory:
    def __init__(self, index=""):
        self._index = index
    def load_index(self):
        return self._index


def test_root_system_prompt_includes_memory_block(tmp_path):
    store = _FakeMemory(index="# Memory index\n- wp-prefs (user): likes sentence case\n")
    agent = Agent(FakeClient([ChatResult(content="ok")]), allowed_roots=[tmp_path],
                  cwd=tmp_path, approval=_AllowAll(), self_review=False, memory_store=store)
    sys_content = agent.messages[0]["content"]
    assert "What you remember" in sys_content
    assert "wp-prefs (user): likes sentence case" in sys_content


def test_memory_tools_present_only_with_store(tmp_path):
    store = _FakeMemory()
    agent, client = make_agent(tmp_path, [ChatResult(content="ok")], memory_store=store)
    agent.run("hi")
    names = {t["function"]["name"] for t in client.last_tools}
    assert "remember" in names and "read_memory" in names


def test_no_memory_tools_without_store(tmp_path):
    agent, client = make_agent(tmp_path, [ChatResult(content="ok")])
    agent.run("hi")
    names = {t["function"]["name"] for t in client.last_tools}
    assert "remember" not in names
    assert "What you remember" not in agent.messages[0]["content"]


def test_child_has_no_memory_store(tmp_path):
    store = _FakeMemory(index="# Memory index\n- x (user): y\n")
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False, memory_store=store,
                  on_text=lambda s: None)
    child = agent._make_child(None, None)
    assert child.memory_store is None
    assert "What you remember" not in child.messages[0]["content"]


def test_run_children_returns_reports_in_order(tmp_path):
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False, on_text=lambda s: None)

    class _C:
        def __init__(self, r): self._r = r
        def run(self, task): return self._r
        def close(self): pass

    seq = iter([_C("first"), _C("second")])
    agent._make_child = lambda role, instructions, **kw: next(seq)
    out = agent._run_children([
        {"prompt": "a", "label": "x"}, {"prompt": "b", "label": "y"}])
    assert out == [("x", "first"), ("y", "second")]


def test_run_children_default_label(tmp_path):
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False, on_text=lambda s: None)

    class _C:
        def run(self, task): return "r"
        def close(self): pass
    agent._make_child = lambda role, instructions, **kw: _C()
    out = agent._run_children([{"prompt": "a"}])  # no label → parallel_label
    assert out[0][0] == "agent#1"


def test_review_changes_delegates(tmp_path, monkeypatch):
    import heya.review as review_mod
    captured = {}
    def fake_run_review(target, *, run_children, git_diff_fn, reviewers, standards="", **kw):
        captured["target"] = target
        captured["standards"] = standards
        return "VERDICT TEXT"
    monkeypatch.setattr(review_mod, "run_review", fake_run_review)
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False)
    assert agent._review_changes("branch") == "VERDICT TEXT"
    assert captured["target"] == "branch"


def test_loop_exposes_review_changes(tmp_path):
    agent, client = make_agent(tmp_path, [ChatResult(content="ok")])
    agent.run("hi")
    names = {t["function"]["name"] for t in client.last_tools}
    assert "review_changes" in names  # root agent gets the review tool


def test_review_panel_focus(tmp_path):
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False)
    full = agent._review_panel("all")
    assert len(full) == 4
    sec = agent._review_panel("security")
    assert len(sec) == 1 and sec[0][0] == "security-reviewer"
    corr = agent._review_panel("correctness")
    assert len(corr) == 1 and corr[0][0] == "code-reviewer"
    assert agent._review_panel("bogus") == full  # unknown focus → full panel


def test_review_changes_filters_by_focus(tmp_path, monkeypatch):
    import heya.review as review_mod
    captured = {}
    def fake_run_review(target, *, run_children, git_diff_fn, reviewers, standards="", **kw):
        captured["reviewers"] = reviewers
        return "ok"
    monkeypatch.setattr(review_mod, "run_review", fake_run_review)
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False)
    agent._review_changes("branch", "security")
    assert len(captured["reviewers"]) == 1
    assert captured["reviewers"][0][0] == "security-reviewer"


def test_review_reviewers_panel_has_four(tmp_path):
    agent = Agent(FakeClient([]), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False)
    labels = [r[0] for r in agent.REVIEW_REVIEWERS]
    assert labels == ["code-reviewer", "security-reviewer", "standards-reviewer", "minimalism-reviewer"]
    # the security reviewer carries the taint methodology (4-tuple)
    sec = next(r for r in agent.REVIEW_REVIEWERS if r[0] == "security-reviewer")
    assert "wp_verify_nonce" in sec[3]


from heya.llm_client import Usage
from heya.context import SUMMARY_MARKER


class FakeChatClient:
    """Records .chat() calls; returns a scripted ChatResult or raises."""

    def __init__(self, result=None, raises=False):
        self.result = result
        self.raises = raises
        self.calls = []

    def chat(self, messages):
        self.calls.append([dict(m) for m in messages])
        if self.raises:
            raise RuntimeError("weak down")
        return self.result


def test_weak_client_defaults_to_main(tmp_path):
    agent, client = make_agent(tmp_path, [ChatResult(content="x")])
    assert agent.weak_client is agent.client
    assert agent.weak_tokens == 0


def test_weak_chat_routes_to_weak_and_buckets_tokens(tmp_path):
    weak = FakeChatClient(ChatResult(content="summary", usage=Usage(10, 5)))
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")], weak_client=weak)
    out = agent._weak_chat([{"role": "user", "content": "hi"}])
    assert out.content == "summary"
    assert len(weak.calls) == 1
    assert agent.weak_tokens == 15      # 10 + 5
    assert agent.session_tokens == 0    # weak tokens never hit the main counters
    assert agent._task_tokens == 0


def test_weak_chat_falls_back_to_main_on_failure(tmp_path):
    weak = FakeChatClient(raises=True)
    warnings = []
    agent, _ = make_agent(
        tmp_path, [ChatResult(content="x")],
        weak_client=weak, on_text=warnings.append,
    )
    # Patch the main client with a chat() that succeeds.
    agent.client = FakeChatClient(ChatResult(content="main-summary", usage=Usage(7, 3)))
    out = agent._weak_chat([{"role": "user", "content": "hi"}])
    assert out.content == "main-summary"
    assert agent.session_tokens == 10   # fallback tokens billed to main
    assert agent.weak_tokens == 0
    assert any("weak model unavailable" in w for w in warnings)


def test_weak_chat_main_equals_weak_buckets_to_session(tmp_path):
    # No weak profile: weak_client is the main client; summary tokens are main's.
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")])
    agent.client = FakeChatClient(ChatResult(content="s", usage=Usage(4, 1)))
    agent.weak_client = agent.client
    out = agent._weak_chat([{"role": "user", "content": "hi"}])
    assert out.content == "s"
    assert agent.session_tokens == 5
    assert agent.weak_tokens == 0


def test_weak_chat_propagates_when_both_fail(tmp_path):
    # Both weak and main fail: exception must propagate (compact() handles).
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")],
                          weak_client=FakeChatClient(raises=True))
    agent.client = FakeChatClient(raises=True)
    assert agent.weak_client is not agent.client  # ensure they are distinct
    with pytest.raises(RuntimeError, match="weak down"):
        agent._weak_chat([{"role": "user", "content": "hi"}])


def test_summarizer_uses_weak_client(tmp_path):
    weak = FakeChatClient(ChatResult(content="THE SUMMARY", usage=Usage(2, 2)))
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")], weak_client=weak)
    middle = [
        {"role": "user", "content": "do a thing"},
        {"role": "assistant", "content": "did the thing"},
    ]
    note = agent._summarize(middle)
    assert "THE SUMMARY" in note
    assert len(weak.calls) == 1


def test_agent_accumulates_usage(tmp_path):
    scripted = [ChatResult(content="done", usage=Usage(10, 5))]
    agent, _ = make_agent(tmp_path, scripted)
    agent.run("hi")
    assert agent._task_tokens == 15
    assert agent.session_tokens == 15


def test_agent_stops_at_token_budget(tmp_path):
    # budget tiny; first call spends over it → the loop stops before a second call.
    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="read_file",
            arguments='{"path": "x"}')], usage=Usage(100, 100)),
        ChatResult(content="should not be reached"),
    ]
    (tmp_path / "x").write_text("data")
    client = FakeClient(scripted)
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False, task_token_budget=50)
    answer = agent.run("go")
    assert "token budget" in answer.lower()
    assert len(client.calls) == 1            # stopped before the second call


def test_agent_budget_zero_is_unlimited(tmp_path):
    scripted = [ChatResult(content="a", usage=Usage(10_000, 10_000)),
                ChatResult(content="b", usage=Usage(10_000, 10_000))]
    # two turns, huge usage, budget 0 → never stops on budget
    agent, _ = make_agent(tmp_path, scripted, task_token_budget=0)
    assert agent.run("one") == "a"
    assert agent.run("two") == "b"


def test_agent_compacts_when_over_window(tmp_path):
    # tiny window forces compaction; the assistant's final turn answers after compaction.
    # Two tool-call rounds: the first (big) result ends up in middle and gets microcompacted;
    # the second (small) result ends up in the recent tail (kept verbatim).
    big = "Z" * 8000
    x_path = str(tmp_path / "x")
    y_path = str(tmp_path / "y")
    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="read_file",
            arguments=f'{{"path": "{x_path}"}}')], usage=Usage(5, 5)),
        ChatResult(content=None, tool_calls=[ToolCall(id="2", name="read_file",
            arguments=f'{{"path": "{y_path}"}}')], usage=Usage(5, 5)),
        ChatResult(content="final answer", usage=Usage(5, 5)),
    ]
    (tmp_path / "x").write_text(big)   # big result → over window, ends up in middle
    (tmp_path / "y").write_text("tiny")  # small result → stays in tail
    client = FakeClient(scripted)
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False, context_window=200, compaction_threshold=1.0,
                  reserve_tokens=0, keep_recent_tokens=40)
    answer = agent.run("read x then y")
    assert answer == "final answer"
    # the big tool output was microcompacted (stubbed) before the third call
    third_call_msgs = client.calls[2]
    assert any("omitted to save context" in (m.get("content") or "") for m in third_call_msgs)


def test_make_child_weak_uses_weak_client(tmp_path):
    weak = FakeChatClient(ChatResult(content="x"))
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")], weak_client=weak)
    child = agent._make_child(None, None, weak=True)
    assert child.client is weak               # child's primary client is the weak one
    assert child.weak_client is weak          # and its weak slot too
    assert "weak" in child.label


def test_make_child_default_uses_main_client(tmp_path):
    weak = FakeChatClient(ChatResult(content="x"))
    agent, client = make_agent(tmp_path, [ChatResult(content="x")], weak_client=weak)
    child = agent._make_child(None, None)
    assert child.client is client             # main by default
    assert child.weak_client is weak          # weak reference still threaded


def test_review_children_use_main_client_not_weak(tmp_path):
    weak = FakeChatClient(ChatResult(content="x"))
    agent, client = make_agent(tmp_path, [ChatResult(content="x")], weak_client=weak)
    captured = []
    orig = agent._make_child

    def spy(role, instructions, **kw):
        ch = orig(role, instructions, **kw)
        captured.append(ch)
        return ch

    agent._make_child = spy
    agent._run_children([
        {"prompt": "review this"},
    ])
    assert captured, "expected at least one review child"
    assert all(ch.client is client for ch in captured)
    assert all(ch.client is not weak for ch in captured)


def test_agent_record_verdict_gate_downgrades_without_evidence(tmp_path):
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")])
    # No evidence -> a "reproduced" verdict must be written as "blocked".
    out = agent._record_repro_verdict(
        slug="WOO-1", verdict="reproduced", evidence=[],
        what_happens="w", summary="s", version_results=[], suggested_next_step="n",
    )
    assert "blocked" in out
    report = (tmp_path / "repro" / "WOO-1" / "report.md").read_text()
    assert "**Verdict:** blocked" in report


def test_agent_start_reproduction_thin_report_builds_nothing(tmp_path):
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")])
    out = agent._start_reproduction(steps=[], expected="", actual="")
    assert "blocked" in out.lower()
    assert not (tmp_path / "repro").exists()


def test_agent_start_reproduction_full_writes_spec(tmp_path):
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")])
    out = agent._start_reproduction(
        slug="WOO-2", steps=["a"], expected="b", actual="c", wp_version="6.5",
    )
    assert "WOO-2" in out
    assert (tmp_path / "repro" / "WOO-2" / "repro-spec.json").is_file()


def test_agent_diagnose_issue_writes_diagnosis(tmp_path, monkeypatch):
    import heya.agent as agent_mod
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")])
    # Seed a working folder with a spec (as 12a would).
    base = tmp_path / "repro" / "WOO-9"
    (base / "evidence").mkdir(parents=True)
    (base / "repro-spec.json").write_text('{"source": "WOO-9", "steps": ["x"], '
                                          '"expected": "a", "actual": "b", "wp_version": "6.5"}')

    # Stub run_diagnosis so the test is deterministic and offline.
    monkeypatch.setattr(agent_mod, "run_diagnosis",
                        lambda context, evidence, **kw: "## Diagnosis\n**Class:** conflict")
    out = agent._diagnose_issue(slug="WOO-9", evidence="conflict test isolated plugin X",
                                logs="Cannot redeclare foo()")
    assert "WOO-9" in out
    diag = (base / "diagnosis.md").read_text()
    assert "conflict" in diag


def test_agent_diagnose_issue_never_raises_on_missing_spec(tmp_path, monkeypatch):
    import heya.agent as agent_mod
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")])
    # Patch run_diagnosis so the test is offline/deterministic; the point is that
    # a missing repro-spec.json does not raise (the else-branch handles it).
    monkeypatch.setattr(agent_mod, "run_diagnosis",
                        lambda context, evidence, **kw: "## Diagnosis\ninsufficient evidence")
    out = agent._diagnose_issue(slug="does-not-exist", evidence="", logs="")
    assert isinstance(out, str)
    assert "diagnosis" in out.lower()
    assert (tmp_path / "repro" / "does-not-exist" / "diagnosis.md").is_file()


def test_agent_record_fix_verdict_gate_and_write(tmp_path):
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")])
    base = tmp_path / "repro" / "WOO-7"
    (base / "evidence").mkdir(parents=True)
    (base / "repro-spec.json").write_text('{"source": "WOO-7", "steps": ["x"], '
                                          '"expected": "a", "actual": "b", "wp_version": "6.5"}')
    # Regression fails -> must be recorded not-verified despite repro passing.
    out = agent._record_fix_verdict(slug="WOO-7", repro_passes=True, regression_passes=False,
                                    evidence=["repro passes"], kind="snippet",
                                    content="<?php return 1;", how_to_apply="snippet plugin",
                                    caveats="")
    assert "not-verified" in out
    sol = (base / "solution.md").read_text()
    assert "**Verdict:** not-verified" in sol
    assert "unsupported workaround" in sol.lower()


def test_agent_record_fix_verdict_bounds_the_loop(tmp_path):
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")])
    base = tmp_path / "repro" / "WOO-loop"
    (base / "evidence").mkdir(parents=True)
    (base / "repro-spec.json").write_text('{"source": "WOO-loop", "wp_version": "6.5"}')
    # Three distinct not-verified attempts, then a fourth: the durable attempt log
    # must tell the agent to STOP (the bound is enforced in code, not just prompt).
    outs = []
    for i in range(4):
        outs.append(agent._record_fix_verdict(
            slug="WOO-loop", repro_passes=False, regression_passes=False,
            evidence=[f"still failing v{i}"], kind="patch", content=f"diff version {i}",
            how_to_apply="apply", caveats=""))
    assert "STOP" in outs[-1]
    import json as _json
    log = _json.loads((base / "attempts.json").read_text())
    assert len(log) == 4 and all(not a["verified"] for a in log)


def test_agent_check_remediation_runs_grounding(tmp_path, monkeypatch):
    import heya.agent as agent_mod
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")])
    base = tmp_path / "repro" / "WOO-8"
    (base / "evidence").mkdir(parents=True)
    (base / "repro-spec.json").write_text('{"source": "WOO-8", "steps": ["x"], '
                                          '"expected": "a", "actual": "b", "wp_version": "6.5"}')
    monkeypatch.setattr(agent_mod, "verify_remediation",
                        lambda fix, context, **kw: "grounded: ok")
    out = agent._check_remediation(slug="WOO-8", kind="setting", content='{"a": "b"}')
    assert "grounded" in out.lower()
    assert "valid json" in out.lower() or "safe" in out.lower()


def test_agent_diagnose_escalates_then_blocks(tmp_path, monkeypatch):
    import heya.agent as agent_mod
    from heya.diagnosis import synthesize_diagnosis
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")])
    base = tmp_path / "repro" / "WOO-esc"
    (base / "evidence").mkdir(parents=True)
    (base / "repro-spec.json").write_text('{"source": "WOO-esc", "wp_version": "6.5"}')
    monkeypatch.setattr(agent_mod, "run_diagnosis",
                        lambda context, evidence, **kw: synthesize_diagnosis([]))
    out1 = agent._diagnose_issue(slug="WOO-esc", evidence="", logs="")
    assert "escalation round 1" in out1.lower()
    out2 = agent._diagnose_issue(slug="WOO-esc", evidence="", logs="")
    assert "escalation round 2" in out2.lower()
    out3 = agent._diagnose_issue(slug="WOO-esc", evidence="", logs="")
    assert "blocked" in out3.lower() and "insufficient evidence after 3 rounds" in out3.lower()


def test_agent_diagnose_grounded_resets_counter(tmp_path, monkeypatch):
    import heya.agent as agent_mod
    import json as _json
    from heya.diagnosis import synthesize_diagnosis, Hypothesis
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")])
    base = tmp_path / "repro" / "WOO-reset"
    (base / "evidence").mkdir(parents=True)
    (base / "repro-spec.json").write_text('{"source": "WOO-reset", "wp_version": "6.5"}')
    monkeypatch.setattr(agent_mod, "run_diagnosis",
                        lambda context, evidence, **kw: synthesize_diagnosis([]))
    agent._diagnose_issue(slug="WOO-reset", evidence="", logs="")
    assert _json.loads((base / "diagnosis-rounds.json").read_text()) == 1
    monkeypatch.setattr(agent_mod, "run_diagnosis",
                        lambda context, evidence, **kw: synthesize_diagnosis(
                            [Hypothesis("conflict", "x", ("e",), ("f.php",), "high")]))
    agent._diagnose_issue(slug="WOO-reset", evidence="", logs="")
    assert _json.loads((base / "diagnosis-rounds.json").read_text()) == 0


def test_agent_exposes_skills_block_and_tool(tmp_path):
    from heya.skills import SkillItem
    sd = tmp_path / "greet"
    (sd).mkdir()
    (sd / "SKILL.md").write_text("---\nname: greet\ndescription: greets people\n---\nSay hi to $ARGUMENTS.")
    skills = {"greet": SkillItem("greet", "greets people", "", sd, (), sd / "SKILL.md")}
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")], skills=skills)
    # skills block injected into the system prompt
    assert "greet: greets people" in agent.messages[0]["content"]
    # _skill loads the body with substitution
    out = agent._skill("greet", "Sam")
    assert "Say hi to Sam." in out
    # unknown skill -> error with available names
    assert "unknown skill" in agent._skill("nope").lower()


def test_agent_no_skills_no_block(tmp_path):
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")])
    assert "Skills available" not in agent.messages[0]["content"]


def test_collect_skills_into_agent(tmp_path):
    from heya.skills import collect_skills
    sd = tmp_path / "wp-fix"
    sd.mkdir()
    (sd / "SKILL.md").write_text("---\nname: wp-fix\ndescription: fixes WP issues\n---\nDo the fix.")
    skills = collect_skills([tmp_path])
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")], skills=skills)
    assert "wp-fix: fixes WP issues" in agent.messages[0]["content"]
    assert "Do the fix." in agent._skill("wp-fix")


def test_plugin_skill_reaches_agent(tmp_path):
    from heya.plugins import discover_plugins, collect_plugin_skills
    root = tmp_path / "cache" / "mkt" / "superpowers" / "1.0.0"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text('{"name": "superpowers"}')
    sd = root / "skills" / "brainstorm"
    sd.mkdir(parents=True)
    (sd / "SKILL.md").write_text("---\nname: brainstorm\ndescription: ideate\n---\nBrainstorm now.")
    skills = collect_plugin_skills(discover_plugins([tmp_path]))
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")], skills=skills)
    assert "superpowers:brainstorm: ideate" in agent.messages[0]["content"]
    assert "Brainstorm now." in agent._skill("superpowers:brainstorm")


def test_agent_pretooluse_hook_blocks(tmp_path):
    from heya.hooks import HookSpec
    from heya.llm_client import ToolCall
    # A PreToolUse hook on run_command that exits 2 -> the tool is blocked.
    spec = HookSpec("PreToolUse", "run_command", "x.sh", (), 5.0, "cfg")
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")],
                          hooks={"PreToolUse": [spec]}, hooks_enabled=True, session_id="s")
    agent._run_hook_command = lambda s, *, stdin: (2, "", "blocked by policy")
    call = ToolCall(id="1", name="run_command", arguments='{"command": "echo hi"}')
    out = agent._handle_call(call)
    assert "blocked by policy" in out.lower() or "pretooluse" in out.lower()


def test_agent_hooks_disabled_do_not_fire(tmp_path):
    from heya.hooks import HookSpec
    from heya.llm_client import ToolCall
    spec = HookSpec("PreToolUse", "*", "x.sh", (), 5.0, "cfg")
    fired = []
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")],
                          hooks={"PreToolUse": [spec]}, hooks_enabled=False, session_id="s")
    agent._run_hook_command = lambda s, *, stdin: fired.append(1) or (2, "", "x")
    call = ToolCall(id="1", name="read_file", arguments='{"path": "x"}')
    agent._handle_call(call)
    assert fired == []  # disabled -> never runs


def test_agent_sessionstart_and_stop_fire(tmp_path):
    from heya.hooks import HookSpec
    spec_start = HookSpec("SessionStart", "", "s.sh", (), 5.0, "cfg")
    spec_stop = HookSpec("Stop", "", "e.sh", (), 5.0, "cfg")
    events = []
    agent, _ = make_agent(tmp_path, [ChatResult(content="done")],
                          hooks={"SessionStart": [spec_start], "Stop": [spec_stop]},
                          hooks_enabled=True, session_id="s")
    agent._run_hook_command = lambda s, *, stdin: events.append(s.event) or (0, "", "")
    agent.run("hello")
    assert "SessionStart" in events and "Stop" in events


def test_hooks_collected_and_fire(tmp_path):
    import json as _json
    from heya.hooks import collect_hooks
    settings = tmp_path / "settings.json"
    settings.write_text(_json.dumps({"hooks": {"SessionStart": [
        {"hooks": [{"type": "command", "command": "start.sh"}]}]}}))
    hooks = collect_hooks([settings])
    fired = []
    agent, _ = make_agent(tmp_path, [ChatResult(content="ok")],
                          hooks=hooks, hooks_enabled=True, session_id="s")
    agent._run_hook_command = lambda s, *, stdin: fired.append(s.event) or (0, "", "")
    agent.run("hi")
    assert "SessionStart" in fired


def test_spawn_agent_uses_discovered_role(tmp_path):
    from heya.subagents import Role
    role = Role(name="sec", system_addendum="You are a security reviewer.",
                tools=frozenset({"read_file"}))
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")], agent_roles={"sec": role})
    # the discovered role is listed in the system prompt
    assert "sec" in agent.messages[0]["content"]
    child = agent._make_child(role, None)
    assert child.tool_filter == frozenset({"read_file"})


def test_spawn_agent_unknown_role_lists_discovered(tmp_path):
    from heya.subagents import Role
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")],
                          agent_roles={"sec": Role("sec", "addendum", None)})
    out = agent._spawn_agent("do x", role="ghost")
    assert "unknown role" in out.lower() and "sec" in out


def test_spawn_agent_builtin_role_still_works(tmp_path):
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")],
                          agent_roles={"sec": __import__("heya.subagents", fromlist=["Role"]).Role("sec", "a", None)})
    # built-in 'researcher' resolves even with discovered roles present
    from heya.subagents import resolve_role
    assert resolve_role("researcher") is not None


def test_command_and_agent_reach_agent(tmp_path):
    from heya.skills import collect_commands
    from heya.agent_defs import discover_agent_roles
    cdir = tmp_path / "commands"; cdir.mkdir()
    (cdir / "deploy.md").write_text("---\nname: deploy\ndescription: ship\n---\nDeploy now.")
    adir = tmp_path / "agents"; adir.mkdir()
    (adir / "sec.md").write_text("---\nname: sec\ndescription: security\ntools: Read\n---\nReview security.")
    skills = collect_commands([cdir])
    roles = discover_agent_roles([adir])
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")], skills=skills, agent_roles=roles)
    assert "deploy: ship" in agent.messages[0]["content"]
    assert "sec" in agent.messages[0]["content"]
    assert "Deploy now." in agent._skill("deploy")


def test_spawn_agents_uses_discovered_role(tmp_path):
    from heya.subagents import Role
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")],
                          agent_roles={"sec": Role("sec", "You are a security reviewer.",
                                                   frozenset({"read_file"}))})
    # A discovered role must NOT be rejected as unknown by the parallel path.
    # _run_parallel builds child specs; resolving the role must succeed.
    out = agent._spawn_agents([{"task": "check", "role": "sec"}])
    assert "unknown role" not in out.lower()


def test_spawn_agent_builtin_role_via_call_site(tmp_path):
    from heya.subagents import Role
    # Even with discovered roles present, a built-in role resolves at the _spawn_agent call site.
    agent, _ = make_agent(tmp_path, [ChatResult(content="report")],
                          agent_roles={"sec": Role("sec", "a", None)})
    out = agent._spawn_agent("investigate", role="researcher")
    assert "unknown role" not in out.lower()


def test_agent_triage_report_writes_and_gates_priority(tmp_path):
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")])
    base = tmp_path / "repro" / "WOO-9"
    (base / "evidence").mkdir(parents=True)
    (base / "repro-spec.json").write_text('{"source": "WOO-9", "wp_version": "6.5"}')
    # priority "close" on a "reproduced" verdict must be downgraded to "medium".
    out = agent._triage_report(slug="WOO-9", verdict="reproduced", what_happens="w",
                               impact="i", priority="close", evidence=["e"],
                               repro_link="http://x", candidate_area="c", next_step="n",
                               version_results=[])
    assert "medium" in out.lower()
    report = (base / "triage-report.md").read_text()
    assert "medium" in report and "reproduced" in report
    assert (base / "triage-comment.md").is_file()


def test_agent_record_pick_list_writes(tmp_path):
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")])
    out = agent._record_pick_list(source="view", items=[
        {"id": "A", "title": "t", "complexity": 2, "route": "ready-to-fix",
         "reason": "clear", "action": "go"}])
    assert "A" in out
    assert (tmp_path / "pick-list.md").is_file()


def test_agent_identity_in_system_prompt(tmp_path):
    from heya.config import Identity
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")], identity=Identity(name="Sam", role="HE"))
    assert "Sam" in agent.messages[0]["content"]
    child = agent._make_child(None, None)
    assert "Sam" in child.messages[0]["content"]  # inherited


def test_agent_no_identity_no_line(tmp_path):
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")])
    assert "You are assisting" not in agent.messages[0]["content"]


def test_agent_on_tool_fires_with_describe(tmp_path):
    from heya.llm_client import ToolCall
    seen = []
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")], on_tool=seen.append)
    call = ToolCall(id="1", name="read_file", arguments='{"path": "x"}')
    agent._handle_call(call)
    assert any("read_file" in s for s in seen)


def test_agent_on_tool_raising_is_safe(tmp_path):
    from heya.llm_client import ToolCall
    def boom(s):
        raise RuntimeError("ui broke")
    agent, _ = make_agent(tmp_path, [ChatResult(content="x")], on_tool=boom)
    call = ToolCall(id="1", name="read_file", arguments='{"path": "x"}')
    out = agent._handle_call(call)  # must not raise
    assert isinstance(out, str)


# ---- security: approval-diff must not read outside the allowlist ----

def test_write_file_diff_does_not_read_outside_allowlist(tmp_path, tmp_path_factory):
    """write_file whose path is outside allowed_roots must NOT render that
    file's contents in the approval diff preview (the file read itself is
    the bypass — the write is also later blocked by the tool's own check)."""
    from io import StringIO
    from heya.approval import ApprovalPolicy, UiApprover
    from heya.ui import UI
    from heya.llm_client import ToolCall

    # A second, distinct tmp directory that is NOT in allowed_roots.
    outside_dir = tmp_path_factory.mktemp("outside")
    secret_file = outside_dir / "secret.txt"
    secret_file.write_text("SECRET_CONTENT_12345", encoding="utf-8")

    # Capture everything the UI writes.
    output = StringIO()
    ui = UI(plain=True, write=output.write)
    approver = UiApprover(ui)
    # Auto-answer "n" to the approval prompt via a stream that yields "n\n".
    ui.stream = StringIO("n\n")
    policy = ApprovalPolicy(approver=approver)

    client = FakeClient([ChatResult(content="ok")])
    agent = Agent(
        client,
        allowed_roots=[tmp_path],
        cwd=tmp_path,
        approval=policy,
        self_review=False,
    )

    call = ToolCall(
        id="sec-1",
        name="write_file",
        arguments=f'{{"path": "{secret_file}", "content": "overwrite"}}',
    )
    agent._handle_call(call)

    rendered = output.getvalue()
    assert "SECRET_CONTENT_12345" not in rendered, (
        "The approval diff must not expose contents of a file outside the allowlist"
    )


def test_write_file_diff_still_shows_for_in_allowlist_path(tmp_path):
    """write_file to an in-allowlist path still shows the diff content."""
    from io import StringIO
    from heya.approval import ApprovalPolicy, UiApprover
    from heya.ui import UI
    from heya.llm_client import ToolCall

    in_path = tmp_path / "notes.txt"
    in_path.write_text("ORIGINAL_CONTENT_99", encoding="utf-8")

    output = StringIO()
    ui = UI(plain=True, write=output.write)
    approver = UiApprover(ui)
    ui.stream = StringIO("n\n")
    policy = ApprovalPolicy(approver=approver)

    client = FakeClient([ChatResult(content="ok")])
    agent = Agent(
        client,
        allowed_roots=[tmp_path],
        cwd=tmp_path,
        approval=policy,
        self_review=False,
    )

    call = ToolCall(
        id="sec-2",
        name="write_file",
        arguments=f'{{"path": "{in_path}", "content": "new content"}}',
    )
    agent._handle_call(call)

    rendered = output.getvalue()
    # The old content appears as a removal in the diff.
    assert "ORIGINAL_CONTENT_99" in rendered, (
        "The approval diff must show the existing content for an in-allowlist file"
    )


def test_system_prompt_has_scoped_minimalism_principle():
    from heya.agent import SYSTEM_PROMPT
    p = SYSTEM_PROMPT.lower()
    # scoped to code, names the guidance, and keeps the safety carve-out
    assert "smallest change" in p
    assert "minimal-code" in p
    assert "never minimize" in p
    # the existing read_guidance convention is still present (no regression)
    assert "read_guidance first" in p
    # no em dash introduced
    assert "—" not in SYSTEM_PROMPT


def test_review_panel_includes_minimalism():
    from heya.agent import Agent
    labels = [r[1] for r in Agent.REVIEW_REVIEWERS]
    assert "minimalism" in labels
    # the minimalism reviewer reads the minimal-code guidance
    mini = [r for r in Agent.REVIEW_REVIEWERS if r[1] == "minimalism"][0]
    assert mini[2] == "minimal-code"


def test_review_panel_focus_selects_minimalism():
    from heya.agent import Agent
    # _review_panel is a plain method using only REVIEW_REVIEWERS; call it on a
    # bare instance via __new__ to avoid constructing the whole Agent.
    a = Agent.__new__(Agent)
    panel = a._review_panel("minimalism")
    assert len(panel) == 1 and panel[0][1] == "minimalism"
    # 'all' still returns the whole panel including minimalism
    assert any(r[1] == "minimalism" for r in a._review_panel("all"))


def test_system_prompt_has_environment_nudge():
    from heya.agent import SYSTEM_PROMPT
    p = SYSTEM_PROMPT.lower()
    assert "environment" in p and "rather than assuming" in p
    assert "read_guidance('environment')" in SYSTEM_PROMPT
    assert "—" not in SYSTEM_PROMPT


def test_cancel_event_stops_the_loop(tmp_path):
    # A script that would keep calling a tool forever if not cancelled.
    calls = [ChatResult(content="", tool_calls=[ToolCall(id="1", name="read_file",
             arguments='{"path": "x"}')])] * 50
    cancel = threading.Event()
    cancel.set()  # already cancelled: the loop must stop on the first check
    agent, _ = make_agent(tmp_path, calls, cancel=cancel)
    assert agent.run("go") == "Stopped: cancelled."


def test_write_guard_blocks_write_file(tmp_path):
    blocked_path = tmp_path / "blocked.txt"
    calls = [ChatResult(content="", tool_calls=[ToolCall(id="1", name="write_file",
             arguments=f'{{"path": "{blocked_path}", "content": "x"}}')]),
             ChatResult(content="done")]
    seen = {}

    def guard(name, args):
        seen["name"] = name
        return "Error: that path is leased by background agent a1."

    agent, _ = make_agent(tmp_path, calls, write_guard=guard)
    agent.run("write it")
    assert seen["name"] == "write_file"
    assert not blocked_path.exists()  # write never happened


def test_write_guard_allows_when_none_returned(tmp_path):
    out_path = tmp_path / "ok.txt"
    calls = [ChatResult(content="", tool_calls=[ToolCall(id="1", name="write_file",
             arguments=f'{{"path": "{out_path}", "content": "hi"}}')]),
             ChatResult(content="done")]
    agent, _ = make_agent(tmp_path, calls, write_guard=lambda name, args: None)
    agent.run("write it")
    assert out_path.read_text() == "hi"


def test_spawn_background_agent_runs_a_child(tmp_path):
    from heya.background import BackgroundRegistry

    # The CHILD's scripted client: it answers with no tools, just a report.
    # The PARENT never loops here; we call the spawn method directly.
    reg = BackgroundRegistry()
    parent, _ = make_agent(tmp_path, [ChatResult(content="parent idle")],
                           background_registry=reg)
    # Give the parent a child client factory by reusing its own client is not
    # possible (single-use script); instead the child uses parent.client which
    # must yield a final answer. Re-script the parent client for the child run:
    parent.client._scripted = [ChatResult(content="child report")]
    out = parent._spawn_background_agent("do a thing", None, None, None, False)
    assert "a1" in out

    import time
    end = time.time() + 2
    while time.time() < end and reg.summaries()[0]["status"] == "running":
        time.sleep(0.01)
    assert "child report" in reg.collect("a1")


def test_spawn_background_without_registry_errors(tmp_path):
    agent, _ = make_agent(tmp_path, [ChatResult(content="idle")])  # no background_registry
    out = agent._spawn_background_agent("do a thing", None, None, None, False)
    assert "Error" in out and "not available" in out


class _DeclineConfirm:
    def check(self, name, detail, label=""):
        return True

    def confirm(self, detail, label=""):
        return False


def test_spawn_background_declined_grant(tmp_path):
    from heya.background import BackgroundRegistry
    reg = BackgroundRegistry()
    agent, _ = make_agent(tmp_path, [ChatResult(content="idle")],
                          background_registry=reg)
    # make_agent forces approval=_AllowAll(); override it to exercise the decline path.
    agent.approval = _DeclineConfirm()
    out = agent._spawn_background_agent("build a plugin", None, None,
                                        str(tmp_path / "plugin"), True)
    assert "Declined" in out
    assert reg.summaries() == []  # nothing was started


def test_wp_tools_appear_when_connector_present(tmp_path):
    class _Conn:
        def list_abilities(self):
            return "abilities here"

    calls = [ChatResult(content="", tool_calls=[ToolCall(id="1", name="wp_abilities", arguments="{}")]),
             ChatResult(content="done")]
    agent, _ = make_agent(tmp_path, calls, wp_connector=_Conn())
    agent.run("list site abilities")
    names = {t["function"]["name"] for t in (agent.client.last_tools or [])}
    assert "wp_abilities" in names


def test_wp_tools_absent_without_connector(tmp_path):
    agent, _ = make_agent(tmp_path, [ChatResult(content="hi")])
    agent.run("hi")
    names = {t["function"]["name"] for t in (agent.client.last_tools or [])}
    assert "wp_abilities" not in names


def test_status_cb_wraps_tool_dispatch(tmp_path):
    from contextlib import contextmanager

    (tmp_path / "a.txt").write_text("hello")
    events = []

    @contextmanager
    def recording_status(label):
        events.append(("enter", label))
        yield
        events.append(("exit", label))

    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="read_file",
            arguments=f'{{"path": "{tmp_path / "a.txt"}"}}')]),
        ChatResult(content="done"),
    ]
    agent, _ = make_agent(tmp_path, scripted, status_cb=recording_status)
    agent.run("read the file")

    assert len(events) == 2
    assert events[0][0] == "enter"
    assert events[1][0] == "exit"
    assert events[0][1] == events[1][1]  # same label for enter and exit
