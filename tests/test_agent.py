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
    agent._make_child = lambda role, instructions: _StubChild()
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
    agent._make_child = lambda role, instructions: boom
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
