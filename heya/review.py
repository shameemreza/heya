"""Deterministic code-review pipeline: gather a diff, fan out read-only reviewers,
adversarially verify each finding, synthesize a severity-gated verdict.

The verify pass always runs — it is the load-bearing false-positive control — and
the verdict never fabricates: zero surviving findings yields an explicit pass.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .tools_files import resolve_in_allowlist

SEVERITIES = ("Blocker", "High", "Medium", "Nit")
_SEV_INDEX = {s.lower(): s for s in SEVERITIES}


def normalize_severity(s: str) -> str:
    return _SEV_INDEX.get((s or "").strip().lower(), "Medium")


@dataclass(frozen=True)
class Finding:
    file: str
    line: int | None
    severity: str
    category: str
    title: str
    evidence: str
    suggestion: str


def _parse_block(block: str) -> Finding | None:
    fields: dict[str, str] = {}
    for raw in block.splitlines():
        if ":" in raw:
            key, _, value = raw.partition(":")
            fields[key.strip().lower()] = value.strip()
    if not fields.get("file") or not fields.get("title"):
        return None  # a finding needs at least a file and a title
    line_raw = fields.get("line", "")
    try:
        line = int(line_raw) if line_raw else None
    except ValueError:
        line = None
    return Finding(
        file=fields["file"],
        line=line,
        severity=normalize_severity(fields.get("severity", "Medium")),
        category=fields.get("category", ""),
        title=fields["title"],
        evidence=fields.get("evidence", ""),
        suggestion=fields.get("suggestion", ""),
    )


def parse_findings(text: str) -> list[Finding]:
    """Parse `### FINDING` … `### END` blocks; tolerant (skips malformed blocks)."""
    findings: list[Finding] = []
    for chunk in (text or "").split("### FINDING"):
        if "### END" not in chunk:
            continue
        block = chunk.split("### END", 1)[0]
        f = _parse_block(block)
        if f is not None:
            findings.append(f)
    return findings


def synthesize(findings: list[Finding]) -> str:
    # dedupe by (file, line, title)
    seen = set()
    unique: list[Finding] = []
    for f in findings:
        key = (f.file, f.line, f.title)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    if not unique:
        return "Review complete — nothing blocks. No issues found that would block this change."
    by_sev = {s: [f for f in unique if f.severity == s] for s in SEVERITIES}
    counts = ", ".join(f"{len(by_sev[s])} {s}" for s in SEVERITIES if by_sev[s])
    lines = [f"Review: {len(unique)} finding(s) — {counts}.", ""]
    for sev in ("Blocker", "High", "Medium"):
        for f in by_sev[sev]:
            loc = f"{f.file}:{f.line}" if f.line is not None else f.file
            lines.append(f"[{sev}] {loc} — {f.title}")
            if f.evidence:
                lines.append(f"    evidence: {f.evidence}")
            if f.suggestion:
                lines.append(f"    fix: {f.suggestion}")
    nits = by_sev["Nit"]
    if nits:
        lines.append("")
        lines.append(f"{len(nits)} nit(s): " + "; ".join(f.title for f in nits))
    return "\n".join(lines)


def git_diff(target, *, allowed_roots: Sequence[Path], cwd, runner) -> str:
    """Resolve a review target to a unified diff. `runner(argv, cwd) -> (code, out, err)`.

    target: "branch" (vs merge-base with origin/HEAD or main), "staged", or a path.
    Returns a clean message (never raises) on non-repo / empty diff.
    """
    safe_cwd = resolve_in_allowlist(cwd, allowed_roots)

    def run(argv):
        return runner(argv, str(safe_cwd))

    if target == "staged":
        code, out, err = run(["git", "diff", "--cached"])
    elif target == "branch":
        base_code, base_out, base_err = run(["git", "merge-base", "HEAD", "main"])
        if base_code != 0:
            return _git_error(base_err)
        base = base_out.strip()
        code, out, err = run(["git", "diff", base, "HEAD"])
    else:
        # treat target as a path to diff (working tree changes for that path)
        safe = resolve_in_allowlist(target, allowed_roots)
        code, out, err = run(["git", "diff", "--", str(safe)])
    if code != 0:
        return _git_error(err)
    if not out.strip():
        return "Nothing to review — the diff is empty."
    return out


def _git_error(stderr: str) -> str:
    msg = (stderr or "").strip().splitlines()
    detail = msg[0] if msg else "git command failed"
    return f"Could not get a diff: {detail}"
