"""Deterministic code-review pipeline: gather a diff, fan out read-only reviewers,
adversarially verify each finding, synthesize a severity-gated verdict.

The verify pass always runs — it is the load-bearing false-positive control — and
the verdict never fabricates: zero surviving findings yields an explicit pass.
"""
from __future__ import annotations

from dataclasses import dataclass

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
