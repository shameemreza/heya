"""Triage deliverables: the paste-ready report + comment and the backlog pick-list.

Pure rendering over the artifacts the diagnostic stages already wrote. The
decision bar (verdict, impact, suggested priority, evidence, one-click repro,
next step) is what makes the output usable by a non-developer. Never posts;
nothing here raises (callers wrap). No regex. Mirrors heya/reproduction.py."""

from __future__ import annotations

PRIORITIES = ("high", "medium", "low", "close")
ROUTES = ("ready-to-fix", "triage-first", "needs-info", "skip")
CLOSEABLE = ("fixed-since-report", "cannot-reproduce")


def gate_priority(priority: str, verdict: str) -> str:
    """Normalize the suggested priority. `close` is only valid when the repro
    verdict means the ticket can close; otherwise downgrade to `medium`."""
    p = (priority or "").strip().lower()
    if p not in PRIORITIES:
        return "medium"
    if p == "close" and verdict not in CLOSEABLE:
        return "medium"
    return p


def _bullets(items) -> str:
    return "\n".join(f"- {x}" for x in items) if items else "- (none)"


def _matrix(version_results) -> str:
    rows = "\n".join(f"| {env} | {res} |" for env, res in version_results)
    return "| Environment | Result |\n|---|---|\n" + (rows or "| (none) | (none) |")


def render_triage_report(ctx, *, verdict, what_happens, impact, priority, evidence,
                         repro_link, candidate_area, next_step, version_results,
                         diagnosis_summary="", solution_summary="") -> str:
    parts = [
        f"## Triage report: {ctx.source or '(no source)'}",
        f"**Verdict:** {verdict}",
        f"**What happens:** {what_happens}",
        f"**Version matrix:**\n{_matrix(version_results)}",
        f"**Impact:** {impact}",
        f"**Suggested priority:** {priority} (suggestion; the owning team decides)",
        f"**Evidence:**\n{_bullets(evidence)}",
        f"**One-click repro:** {repro_link or '(none)'}",
    ]
    if diagnosis_summary.strip():
        parts.append(f"**Diagnosis:** {diagnosis_summary.strip()}")
    if solution_summary.strip():
        parts.append(f"**Proposed fix:** {solution_summary.strip()}")
    parts.append(f"**Candidate area:** {candidate_area or '(none)'}")
    parts.append(f"**Suggested next step:** {next_step}")
    return "\n\n".join(parts) + "\n"


def render_triage_comment(ctx, *, verdict, what_happens, impact, priority, evidence,
                          repro_link, next_step) -> str:
    return (
        f"{what_happens}\n\n"
        f"Verdict: {verdict}. {impact}\n\n"
        f"Suggested priority: {priority} (the owning team decides).\n\n"
        f"Evidence:\n{_bullets(evidence)}\n\n"
        f"One-click repro: {repro_link or '(none)'}\n\n"
        f"Suggested next step: {next_step}\n"
    )


def render_pick_list(source: str, items) -> str:
    if not items:
        return f"## Pick list: {source}\n\nNo open issues to rank.\n"
    lines = [f"## Pick list: {source}", ""]
    for i, item in enumerate(items, 1):
        route = (item.get("route") or "").strip()
        reason = item.get("reason", "")
        if route not in ROUTES:
            route, reason = "skip", f"(invalid route) {reason}".strip()
        title = item.get("title", "")
        ident = item.get("id", "")
        complexity = item.get("complexity", "?")
        action = item.get("action", "")
        lines.append(f"{i}. {ident} {title}".rstrip())
        lines.append(f"   Complexity {complexity}/10. {reason}")
        lines.append(f"   Route: {route}. {action}".rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
