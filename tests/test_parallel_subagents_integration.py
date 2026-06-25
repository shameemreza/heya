"""End-to-end: a parent fans out two read-only children with spawn_agents; they
run concurrently, stream labeled output, return submission-ordered reports, and
do not close shared sessions."""
import threading

from heya.agent import Agent
from heya.llm_client import ChatResult, ToolCall
from heya.subagents import SUBAGENT_FRAMING


class ThreadSafeFakeClient:
    """Returns scripted results by inspecting messages (call order is nondeterministic
    under concurrency), so it is safe to call from multiple child threads at once."""

    def __init__(self):
        self._lock = threading.Lock()
        self.calls = []

    def chat_stream(self, messages, tools=None, on_text=None):
        with self._lock:
            self.calls.append([dict(m) for m in messages])
        system = messages[0]["content"]
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        has_tool_result = any(m["role"] == "tool" for m in messages)
        if SUBAGENT_FRAMING[:24] in system:  # this is a child
            result = ChatResult(content=f"finding for {last_user}")
        elif not has_tool_result:           # parent's first turn → fan out
            result = ChatResult(content=None, tool_calls=[ToolCall(
                id="1", name="spawn_agents",
                arguments='{"tasks": [{"task": "research A", "role": "researcher"},'
                          ' {"task": "review B", "role": "reviewer"}]}')])
        else:                                # parent's second turn → synthesize
            result = ChatResult(content="synthesized both findings")
        if result.content and on_text:
            on_text(result.content)
        return result


class _AllowAll:
    def check(self, name, detail, label=""):
        return True


def test_spawn_agents_runs_two_children_in_parallel(tmp_path):
    class Session:
        closed = False
        def close(self):
            self.closed = True

    out_chunks = []
    lock = threading.Lock()
    def on_text(s):
        with lock:
            out_chunks.append(s)

    session = Session()
    client = ThreadSafeFakeClient()
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False, on_text=on_text, browser_session=session)
    answer = agent.run("delegate the two reviews")

    assert answer == "synthesized both findings"
    # The spawn_agents tool result (in the parent's final turn) holds both child
    # reports, in submission order (researcher task before reviewer task).
    parent_final = client.calls[-1]
    tool_msg = next(m for m in parent_final if m["role"] == "tool")
    body = tool_msg["content"]
    assert "finding for research A" in body
    assert "finding for review B" in body
    assert body.index("research A") < body.index("review B")  # submission order
    # Output was streamed with indexed parallel labels.
    streamed = "".join(out_chunks)
    assert "[researcher#1]" in streamed
    assert "[reviewer#2]" in streamed
    # The fan-out did not close the parent's shared session.
    assert session.closed is False
    agent.close()
    assert session.closed is True


def test_parallel_child_cannot_write(tmp_path):
    # A read-only parallel child that emits a write_file call is refused (tool_filter),
    # proving read-only enforcement end to end.
    class WriterClient:
        def __init__(self):
            self._lock = threading.Lock()
            self.calls = []
        def chat_stream(self, messages, tools=None, on_text=None):
            with self._lock:
                self.calls.append([dict(m) for m in messages])
            system = messages[0]["content"]
            has_tool_result = any(m["role"] == "tool" for m in messages)
            if SUBAGENT_FRAMING[:24] in system:
                if not has_tool_result:  # child tries to write
                    return ChatResult(content=None, tool_calls=[ToolCall(
                        id="w", name="write_file",
                        arguments=f'{{"path": "{tmp_path / "x.txt"}", "content": "hi"}}')])
                return ChatResult(content="could not write; reporting instead")
            if not has_tool_result:
                return ChatResult(content=None, tool_calls=[ToolCall(
                    id="1", name="spawn_agents",
                    arguments='{"tasks": [{"task": "try to write"}]}')])
            return ChatResult(content="done")

    client = WriterClient()
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False)
    agent.run("delegate a write")
    assert not (tmp_path / "x.txt").exists()  # write refused
    # the child saw a "not available" refusal for write_file
    child_turn = next(c for c in client.calls
                      if any(m["role"] == "tool" and "not available" in m["content"] for m in c))
    assert child_turn is not None
