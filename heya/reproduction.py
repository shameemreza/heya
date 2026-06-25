"""Reproduction-stage logic for the diagnostic workflow.

The agent drives the actual reproduction (Playground, browser, wp-cli, logs) in
its own loop. This module provides the two deterministic seams: structured
intake (parse_issue_context) and the evidence-gated verdict + report rendering
(gate_verdict / render_report / render_comment). Pure logic plus one folder
helper; callers in dispatch wrap these so nothing raises into the loop. Mirrors
heya/review.py."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from .tools_files import resolve_in_allowlist

VERDICTS = ("reproduced", "fixed-since-report", "cannot-reproduce", "blocked")


@dataclass(frozen=True)
class IssueContext:
    source: str = ""
    steps: tuple[str, ...] = ()
    expected: str = ""
    actual: str = ""
    wp_version: str = ""
    wc_version: str = ""
    php_version: str = ""
    plugins: tuple[str, ...] = ()
    theme: str = ""
    settings: tuple[str, ...] = ()
    seed_data: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            k: (list(v) if isinstance(v, tuple) else v)
            for k, v in asdict(self).items()
        }


def _as_tuple(value) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    return tuple(str(x).strip() for x in value if str(x).strip())


def parse_issue_context(fields: dict) -> IssueContext:
    """Normalize agent-supplied fields into an IssueContext, computing `missing`
    (required: steps, expected, actual, and at least one of wp/wc/php version)."""
    steps = _as_tuple(fields.get("steps"))
    expected = (fields.get("expected") or "").strip()
    actual = (fields.get("actual") or "").strip()
    wp = (fields.get("wp_version") or "").strip()
    wc = (fields.get("wc_version") or "").strip()
    php = (fields.get("php_version") or "").strip()
    missing = []
    if not steps:
        missing.append("steps")
    if not expected:
        missing.append("expected")
    if not actual:
        missing.append("actual")
    if not (wp or wc or php):
        missing.append("version (wp/wc/php)")
    return IssueContext(
        source=(fields.get("source") or "").strip(),
        steps=steps, expected=expected, actual=actual,
        wp_version=wp, wc_version=wc, php_version=php,
        plugins=_as_tuple(fields.get("plugins")),
        theme=(fields.get("theme") or "").strip(),
        settings=_as_tuple(fields.get("settings")),
        seed_data=_as_tuple(fields.get("seed_data")),
        missing=tuple(missing),
    )


def _safe_slug(slug: str) -> str:
    cleaned = "".join(
        c if (c.isalnum() or c in "-_") else "-" for c in (slug or "").strip()
    )
    cleaned = cleaned.strip("-")
    return (cleaned or "issue")[:64]


def repro_workdir(slug: str, *, allowed_roots: Sequence[Path], cwd: Path) -> Path:
    """Create and return repro/<safe-slug>/ (with an evidence/ subfolder) inside
    the allowlist. The slug is sanitized to a single path segment, then the full
    path is re-checked against the allowed roots."""
    safe = _safe_slug(slug)
    target = resolve_in_allowlist(Path(cwd) / "repro" / safe, allowed_roots)
    (target / "evidence").mkdir(parents=True, exist_ok=True)
    return target


def gate_verdict(verdict: str, evidence) -> str:
    """Fail-closed: a non-blocked verdict is only allowed out when at least one
    evidence artifact backs it; otherwise it is forced to 'blocked'. An unknown
    verdict is also 'blocked'."""
    if verdict == "blocked":
        return "blocked"
    if verdict not in VERDICTS:
        return "blocked"
    return verdict if evidence else "blocked"


def _bullets(items) -> str:
    return "\n".join(f"- {x}" for x in items) if items else "- (none)"


def _matrix(version_results) -> str:
    rows = "\n".join(f"| {env} | {res} |" for env, res in version_results)
    return "| Environment | Result |\n|---|---|\n" + (rows or "| (none) | (none) |")


def render_report(ctx, verdict, evidence, what_happens, summary,
                  version_results, suggested_next_step) -> str:
    return (
        f"## Reproduction report: {ctx.source or '(no source)'}\n\n"
        f"**Verdict:** {verdict}\n\n"
        f"**What happens:** {what_happens}\n\n"
        f"**Version matrix:**\n{_matrix(version_results)}\n\n"
        f"**Steps tried:**\n{_bullets(ctx.steps)}\n\n"
        f"**Expected:** {ctx.expected}\n\n"
        f"**Actual:** {ctx.actual}\n\n"
        f"**Evidence:**\n{_bullets(evidence)}\n\n"
        f"**Summary:** {summary}\n\n"
        f"**Suggested next step:** {suggested_next_step}\n"
    )


def render_comment(ctx, verdict, evidence, what_happens, summary,
                   version_results, suggested_next_step) -> str:
    return (
        f"{what_happens}\n\n"
        f"Verdict: {verdict} ({', '.join(env for env, _ in version_results) or 'n/a'}).\n\n"
        f"{summary}\n\n"
        f"Evidence:\n{_bullets(evidence)}\n\n"
        f"Suggested next step: {suggested_next_step}\n"
    )
