"""End-to-end: a parent agent spawns a child, which is context-isolated,
streams labeled output, shares resources without closing them, and (as a
read-only role) cannot mutate."""
from heya.agent import Agent
from heya.llm_client import ChatResult, ToolCall


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


class _AllowAll:
    def check(self, name, detail, label=""):
        return True


def test_reviewer_child_streams_labeled_and_cannot_write(tmp_path):
    target = tmp_path / "code.py"
    target.write_text("original")
    out_chunks = []
    scripted = [
        # parent delegates to a reviewer
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="spawn_agent",
            arguments='{"task": "review code.py", "role": "reviewer"}')]),
        # child (reviewer) tries to write — should be refused by tool_filter —
        ChatResult(content=None, tool_calls=[ToolCall(id="2", name="write_file",
            arguments=f'{{"path": "{target}", "content": "rewritten"}}')]),
        # child then reports
        ChatResult(content="review: looks fine, no changes made"),
        # parent final
        ChatResult(content="done; reviewer reported no changes"),
    ]
    client = FakeClient(scripted)
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False, on_text=out_chunks.append)
    answer = agent.run("get code.py reviewed")

    assert answer == "done; reviewer reported no changes"
    # The reviewer is read-only: the write was refused and the file is untouched.
    assert target.read_text() == "original"
    # The child's write attempt produced a "not available" refusal in its context.
    child_second_turn = client.calls[2]
    assert any(
        m["role"] == "tool" and "not available" in m["content"]
        for m in child_second_turn
    )
    # Child output was streamed with the [reviewer] label.
    assert any(chunk.startswith("[reviewer] ") for chunk in out_chunks)
    # Parent's final turn holds the child's report.
    assert any(
        m["role"] == "tool" and "looks fine" in m["content"] for m in client.calls[-1]
    )


def test_parent_close_not_triggered_by_child(tmp_path):
    class Session:
        closed = False
        def close(self):
            self.closed = True
    session = Session()
    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="spawn_agent",
            arguments='{"task": "investigate", "role": "researcher"}')]),
        ChatResult(content="child report"),
        ChatResult(content="parent done"),
    ]
    agent = Agent(FakeClient(scripted), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False, browser_session=session)
    agent.run("delegate")
    assert session.closed is False
    agent.close()
    assert session.closed is True  # only the parent's close() tears down
