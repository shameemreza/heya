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
