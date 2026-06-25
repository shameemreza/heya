"""Context-safety helpers: bound tool output so it never floods the model window."""
from __future__ import annotations

_LINE_MARK = "… [line truncated]"


def truncate_output(text: str, *, max_chars: int = 30000, max_line: int = 2000) -> str:
    """Cap each line to max_line chars, then the whole text to max_chars.

    Single minified lines can be megabytes, so the per-line cap runs first.
    The total cap keeps the head and tail (the informative ends) and drops the
    middle, with an explicit marker — matching how Claude Code / OpenHands bound
    large output.
    """
    capped_lines = [
        ln if len(ln) <= max_line else ln[:max_line] + _LINE_MARK
        for ln in text.split("\n")
    ]
    capped = "\n".join(capped_lines)
    if len(capped) <= max_chars:
        return capped
    dropped = len(capped) - max_chars
    half = max_chars // 2
    marker = f"\n… [truncated {dropped} chars] …\n"
    return capped[:half] + marker + capped[-half:]


def estimate_tokens(text: str) -> int:
    """Rough token count without a tokenizer: ~4 chars per token. Over-counts code
    and non-English, which biases the context guard safely toward compacting early."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """Estimate the token size of an OpenAI-style message list (content + tool-call
    arguments + a small per-message envelope)."""
    total = 0
    for m in messages:
        total += estimate_tokens(m.get("content") or "")
        total += 4  # per-message envelope
        for call in m.get("tool_calls") or []:
            fn = call.get("function") or {}
            total += estimate_tokens(fn.get("arguments") or "")
            total += estimate_tokens(fn.get("name") or "")
    return total
