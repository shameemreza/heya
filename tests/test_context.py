from heya.context import group_messages, compact, build_summarizer, SUMMARY_MARKER


def _no_orphans(messages):
    """Every assistant message with tool_calls is followed by matching tool results."""
    for i, m in enumerate(messages):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            ids = {c["id"] for c in m["tool_calls"]}
            following = [x for x in messages[i + 1:i + 1 + len(ids)] if x.get("role") == "tool"]
            assert {x["tool_call_id"] for x in following} == ids, "orphaned tool pair"


def test_group_messages_binds_tool_results():
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}, {"id": "2"}]},
        {"role": "tool", "tool_call_id": "1", "content": "r1"},
        {"role": "tool", "tool_call_id": "2", "content": "r2"},
        {"role": "assistant", "content": "done"},
    ]
    groups = group_messages(msgs)
    assert [len(g) for g in groups] == [1, 1, 3, 1]  # the assistant+2 tools is one group


def test_compact_noop_under_threshold():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}]
    called = []
    out = compact(msgs, context_window=1000, threshold=0.85, reserve_tokens=0,
                  keep_recent_tokens=100, summarize_fn=lambda m: called.append(m) or "x")
    assert out is msgs                # unchanged
    assert called == []               # summarizer not invoked


def test_compact_microcompaction_suffices():
    # A big tool output in the middle; microcompaction stubs it under budget without summarizing.
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "the task"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "X" * 4000},  # ~1000 tokens
        {"role": "user", "content": "recent"},
        {"role": "assistant", "content": "answer"},
    ]
    called = []
    out = compact(msgs, context_window=100, threshold=1.0, reserve_tokens=0,
                  keep_recent_tokens=40, summarize_fn=lambda m: called.append(m) or "SUMMARY")
    assert called == []                                  # microcompaction alone sufficed
    assert any("omitted to save context" in (m.get("content") or "") for m in out)
    assert out[0]["content"] == "s"                      # system kept
    assert any(m.get("content") == "the task" for m in out)  # first task kept
    _no_orphans(out)


def test_compact_summarizes_when_still_over_budget():
    # Many middle prose turns too big even after microcompaction → summarize the middle.
    middle = []
    for i in range(8):
        middle.append({"role": "user", "content": "Q" * 400})
        middle.append({"role": "assistant", "content": "A" * 400})
    msgs = ([{"role": "system", "content": "s"}, {"role": "user", "content": "the task"}]
            + middle + [{"role": "user", "content": "recent"}, {"role": "assistant", "content": "now"}])
    out = compact(msgs, context_window=100, threshold=1.0, reserve_tokens=0,
                  keep_recent_tokens=40, summarize_fn=lambda m: "STRUCTURED SUMMARY")
    joined = "\n".join(m.get("content") or "" for m in out)
    assert SUMMARY_MARKER in joined and "STRUCTURED SUMMARY" in joined
    assert out[0]["content"] == "s" and any(m.get("content") == "the task" for m in out)
    assert any(m.get("content") == "now" for m in out)   # recent tail kept
    assert "Q" * 400 not in joined                        # old middle dropped (summarized)
    _no_orphans(out)


def test_compact_summary_failure_degrades_to_microcompaction():
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "M" * 4000},
        {"role": "user", "content": "recent"},
        {"role": "assistant", "content": "now"},
    ]
    def boom(_):
        raise RuntimeError("summary model down")
    out = compact(msgs, context_window=100, threshold=1.0, reserve_tokens=0,
                  keep_recent_tokens=40, summarize_fn=boom)
    assert out is not None                # no exception
    assert any(m.get("content") == "now" for m in out)
    assert out[0]["content"] == "s"       # system kept
    _no_orphans(out)                      # degraded path is still tool-pair-safe


def test_build_summarizer_calls_chat():
    seen = {}
    class _R:
        content = "the summary"
    def chat_fn(messages, tools=None):
        seen["messages"] = messages
        return _R()
    summarize = build_summarizer(chat_fn)
    out = summarize([{"role": "user", "content": "stuff"}])
    assert out == "the summary"
    assert seen["messages"][0]["role"] == "system"   # the SUMMARY_PROMPT
    assert "stuff" in seen["messages"][1]["content"]
