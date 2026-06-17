from heya.text import truncate_output


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
