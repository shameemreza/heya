"""Context compaction: keep the conversation within the model's window without
losing key facts. Group-boundary-safe so a tool_call/tool pair is never orphaned;
the system message (memory/rules) is always preserved.
"""
from __future__ import annotations

from collections.abc import Callable

from .text import estimate_messages_tokens

SUMMARY_MARKER = "[Earlier conversation summarized]"

SUMMARY_PROMPT = (
    "You are compacting a coding assistant's conversation to save context. Summarize "
    "the messages below into a concise continuation note that preserves everything "
    "needed to continue correctly. Use these sections:\n"
    "Goal: <the user's overall objective>\n"
    "Decisions: <key choices made and why>\n"
    "Files: <files read or edited, with paths>\n"
    "Errors and fixes: <problems hit and how they were resolved>\n"
    "Open questions / pending: <what is unresolved or still to do>\n"
    "Last state: <where things stand and the immediate next step>\n"
    "Quote the user's own requests verbatim where they matter. Be specific and factual; "
    "do not invent. Output only the note."
)

_STUB_MAX = 200  # tool outputs longer than this are stubbed during microcompaction
_STUB = "[earlier tool output omitted to save context — re-run/re-read if needed]"


def group_messages(messages: list[dict]) -> list[list[dict]]:
    """Split into atomic groups: an assistant message with tool_calls binds its
    following tool results into one group; everything else is its own group."""
    groups: list[list[dict]] = []
    i, n = 0, len(messages)
    while i < n:
        m = messages[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            group = [m]
            j = i + 1
            while j < n and messages[j].get("role") == "tool":
                group.append(messages[j])
                j += 1
            groups.append(group)
            i = j
        else:
            groups.append([m])
            i += 1
    return groups


def _flatten(groups: list[list[dict]]) -> list[dict]:
    return [m for g in groups for m in g]


def _microcompact(group: list[dict]) -> list[dict]:
    """Stub large tool-result contents (keeps the messages, so pairing stays intact)."""
    out = []
    for m in group:
        if m.get("role") == "tool" and len(m.get("content") or "") > _STUB_MAX:
            stub = dict(m)
            stub["content"] = _STUB
            out.append(stub)
        else:
            out.append(m)
    return out


def compact(
    messages: list[dict],
    *,
    context_window: int,
    threshold: float,
    reserve_tokens: int,
    keep_recent_tokens: int,
    summarize_fn: Callable[[list[dict]], str],
    estimate_fn: Callable[[list[dict]], int] = estimate_messages_tokens,
) -> list[dict]:
    """Compact the conversation if it is over the threshold, else return it unchanged.
    Never orphans a tool_call/tool pair; never drops the system message."""
    budget = context_window * threshold - reserve_tokens
    if estimate_fn(messages) < budget:
        return messages
    groups = group_messages(messages)
    if len(groups) <= 2:
        return messages
    system, first_task, rest = groups[0], groups[1], groups[2:]
    # recent tail: whole groups from the end summing to keep_recent_tokens
    tail: list[list[dict]] = []
    used = 0
    for g in reversed(rest):
        gt = estimate_fn(g)
        if used + gt > keep_recent_tokens and tail:
            break
        tail.insert(0, g)
        used += gt
    middle = rest[: len(rest) - len(tail)]
    if not middle:
        return messages
    middle_mc = [_microcompact(g) for g in middle]
    candidate = _flatten([system, first_task, *middle_mc, *tail])
    if estimate_fn(candidate) < budget:
        return candidate
    # still over budget → summarize the middle into one note
    try:
        note = summarize_fn(_flatten(middle_mc))
    except Exception:
        note = ""
    if not note.strip():
        return candidate
    summary_msg = {"role": "user", "content": SUMMARY_MARKER + "\n" + note.strip()}
    return _flatten([system, first_task]) + [summary_msg] + _flatten(tail)


def build_summarizer(chat_fn) -> Callable[[list[dict]], str]:
    """Wrap a non-streaming chat function into summarize_fn(middle) -> str."""
    def summarize(middle: list[dict]) -> str:
        rendered = "\n".join(
            f"{m.get('role', '?')}: {(m.get('content') or '')[:4000]}" for m in middle)
        result = chat_fn([
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": rendered},
        ])
        return getattr(result, "content", None) or ""
    return summarize
