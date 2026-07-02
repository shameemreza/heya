from heya.text import estimate_messages_tokens, estimate_tokens, truncate_output


def test_estimate_tokens_empty_is_zero():
    assert estimate_tokens("") == 0
    assert estimate_tokens(None or "") == 0


def test_estimate_tokens_scales_and_is_at_least_one():
    assert estimate_tokens("abcd") == 1          # 4 chars / 4
    assert estimate_tokens("a") == 1             # non-empty floors to 1
    assert estimate_tokens("x" * 400) == 100
    assert estimate_tokens("x" * 4000) > estimate_tokens("x" * 400)  # monotonic


def test_estimate_messages_tokens_counts_content_and_tool_calls():
    messages = [
        {"role": "system", "content": "x" * 40},          # ~10
        {"role": "user", "content": "x" * 40},            # ~10
        {"role": "assistant", "content": "", "tool_calls": [
            {"type": "function", "function": {"name": "read_file", "arguments": "x" * 40}}]},
    ]
    total = estimate_messages_tokens(messages)
    assert total >= 20  # content + tool-call arguments counted
    # adding a message increases the total
    assert estimate_messages_tokens(messages + [{"role": "user", "content": "y" * 40}]) > total


def test_short_text_unchanged():
    assert truncate_output("hello world") == "hello world"


def test_long_line_is_capped():
    out = truncate_output("x" * 5000, max_line=2000)
    assert "… [line truncated]" in out
    # the visible body of the line is bounded
    assert len(out.splitlines()[0]) <= 2000 + len("… [line truncated]")


def test_total_length_capped_with_middle_truncation():
    text = "\n".join(f"line{i}" for i in range(20000))
    out = truncate_output(text, max_chars=1000)
    assert len(out) <= 1000 + 100  # marker overhead
    assert "truncated" in out
    assert out.startswith("line0")          # head kept
    assert out.rstrip().endswith("line19999")  # tail kept


def test_per_line_cap_applied_before_total_cap():
    out = truncate_output("a" * 100 + "\n" + "b" * 100, max_chars=500, max_line=10)
    assert "… [line truncated]" in out


def test_estimate_handles_list_content():
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "hello there"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]}]
    n = estimate_messages_tokens(msgs)
    assert isinstance(n, int) and n > 0  # does not raise; image adds rough cost
