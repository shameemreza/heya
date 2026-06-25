"""End-to-end: a real Agent remembers a fact via the tool, the file + index persist,
the visible note is emitted, and a fresh agent over the same folder sees the index."""
from heya.agent import Agent
from heya.llm_client import ChatResult, ToolCall
from heya.memory import MemoryStore


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


def test_memory_end_to_end(tmp_path):
    notes = []
    store = MemoryStore(tmp_path, notify=notes.append)
    scripted = [
        ChatResult(content=None, tool_calls=[ToolCall(id="1", name="remember",
            arguments='{"name":"wp-prefs","description":"prefers sentence case UI",'
                      '"type":"user","content":"Use sentence case in UI strings."}')]),
        ChatResult(content="noted"),
    ]
    agent = Agent(FakeClient(scripted), allowed_roots=[tmp_path], cwd=tmp_path,
                  approval=_AllowAll(), self_review=False, memory_store=store)
    answer = agent.run("remember my UI preference")

    assert answer == "noted"
    f = tmp_path / "wp-prefs.md"
    assert f.exists()
    text = f.read_text()
    assert "type: user" in text and "sentence case" in text
    assert "wp-prefs" in (tmp_path / "MEMORY.md").read_text()
    assert any("remembered: wp-prefs" in n for n in notes)  # visible note emitted
    assert "sentence case" in store.read("wp-prefs").lower()

    # A fresh agent over the same folder loads the index into its system context.
    store2 = MemoryStore(tmp_path)
    agent2 = Agent(FakeClient([ChatResult(content="ok")]), allowed_roots=[tmp_path],
                   cwd=tmp_path, approval=_AllowAll(), self_review=False, memory_store=store2)
    assert "wp-prefs" in agent2.messages[0]["content"]
