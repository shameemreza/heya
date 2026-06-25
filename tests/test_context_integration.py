"""End-to-end: a conversation that crosses the context window is compacted without
orphaning a tool pair, the agent still answers, and usage is accounted."""
from heya.agent import Agent
from heya.llm_client import ChatResult, ToolCall, Usage


class FakeClient:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []
    def chat_stream(self, messages, tools=None, on_text=None):
        self.calls.append([dict(m) for m in messages])
        result = self._scripted.pop(0)
        if result.content and on_text:
            on_text(result.content)
        return result
    def chat(self, messages, tools=None):
        # the summarizer path (non-streaming); return a canned structured note
        return ChatResult(content="Goal: read files. Last state: done.", usage=Usage(5, 5))


class _AllowAll:
    def check(self, name, detail, label=""):
        return True


def test_long_conversation_is_compacted_and_answers(tmp_path):
    (tmp_path / "a.txt").write_text("A" * 9000)
    (tmp_path / "b.txt").write_text("B" * 9000)
    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="read_file",
            arguments=f'{{"path": "{tmp_path / "a.txt"}"}}')], usage=Usage(5, 5)),
        ChatResult(content=None, tool_calls=[ToolCall(id="2", name="read_file",
            arguments=f'{{"path": "{tmp_path / "b.txt"}"}}')], usage=Usage(5, 5)),
        ChatResult(content="both files read", usage=Usage(5, 5)),
    ]
    client = FakeClient(scripted)
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False, context_window=300, compaction_threshold=1.0,
                  reserve_tokens=0, keep_recent_tokens=60)
    answer = agent.run("read both files")

    assert answer == "both files read"
    assert agent.session_tokens >= 15            # usage accounted across the turns
    # every model call's message list is tool-pair-safe (no orphaned tool_calls)
    for call in client.calls:
        for i, m in enumerate(call):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                want = {c["id"] for c in m["tool_calls"]}
                got = {x["tool_call_id"] for x in call[i + 1:] if x.get("role") == "tool"}
                assert want <= got, "orphaned tool pair after compaction"
    # the system message (carrying any memory/rules) survived every call
    assert all(call[0]["role"] == "system" for call in client.calls)
    # Positively prove compaction actually fired (the no-orphan check alone would
    # pass even if it never ran): the big tool outputs were microcompacted to a stub.
    assert any(
        any("omitted to save context" in (m.get("content") or "") for m in call)
        for call in client.calls
    ), "compaction did not fire — a later call should carry the microcompaction stub"
