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
        base = None
        last_err = ""
        for ref in ("main", "master", "origin/HEAD"):
            base_code, base_out, base_err = run(["git", "merge-base", "HEAD", ref])
            if base_code == 0:
                base = base_out.strip()
                break
            last_err = base_err
        if base is None:
            return _git_error(last_err)
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


REVIEW_OUTPUT_CONTRACT = (
    "Report each issue as a block exactly like this (repeat per issue):\n"
    "### FINDING\n"
    "file: <path>\nline: <number>\nseverity: <Blocker|High|Medium|Nit>\n"
    "category: <bug|security|correctness|style|...>\n"
    "title: <one line>\nevidence: <the concrete code/behavior proving it>\n"
    "suggestion: <the fix>\n### END\n"
    "If you find nothing that matters, reply with exactly: NO FINDINGS\n"
    "Only report issues you can concretely justify from the code — do not pad with "
    "speculation or pure style nits unless they are real. Prefer fewer, higher-signal "
    "findings."
)

WP_SECURITY_METHODOLOGY = (
    "SECURITY REVIEW — apply the taint frame. Report a vulnerability ONLY when "
    "untrusted input reaches a dangerous sink with NO intervening guard.\n"
    "Untrusted sources: $_GET, $_POST, $_REQUEST, $_COOKIE, $_SERVER, and REST/AJAX "
    "request parameters — anything the client controls.\n"
    "Sink -> required guard (a finding requires the guard to be ABSENT on the path):\n"
    "- SQL ($wpdb->query/get_results/get_var/get_col) -> $wpdb->prepare() with %s/%d/%i placeholders.\n"
    "- HTML/attribute/URL/JS output (echo/print) -> esc_html / esc_attr / esc_url / esc_js / wp_kses[_post] at the sink.\n"
    "- A state-changing action (a form/AJAX/admin-post handler that writes or deletes) -> BOTH "
    "wp_verify_nonce/check_admin_referer AND current_user_can. A nonce proves intent, not permission; both are required.\n"
    "- unserialize() on user data -> PHP object injection.\n"
    "- include/require/fopen/file_get_contents with a user-controlled path and '../' -> path traversal / LFI.\n"
    "- An outbound request to a user-controlled URL -> SSRF.\n"
    "- Hardcoded credentials, API keys, or tokens -> secret exposure (report the location and class; do NOT echo the secret value).\n"
    "Severity: a reachable, exploitable SQLi / object-injection / auth-bypass is Blocker; reflected or "
    "stored XSS, or a missing-nonce-and-capability state change, is High; a defense-in-depth gap with no "
    "concrete exploit is at most Medium and usually not worth reporting.\n"
    "Put the concrete source->sink path in `evidence`; set `category` to the vuln class "
    "(sqli, xss, csrf, authz, object-injection, traversal, ssrf, secret). Use read_file and search_files "
    "to confirm no guard exists on the path before reporting.\n"
    "Do NOT report: theoretical issues, defense-in-depth where the input is already validated/escaped, "
    "rate-limiting or DoS concerns, or generic 'could be unsafe' speculation. Only flag what is concretely "
    "exploitable and would block."
)

WP_STANDARDS_METHODOLOGY = (
    "STANDARDS REVIEW — WordPress/WooCommerce coding standards and plugin-directory guidelines. Check: "
    "internationalization (translatable strings via __()/esc_html__() with the correct text domain, escaped "
    "on output); proper hook usage; unique prefixing of functions/classes/options to avoid collisions; input "
    "sanitization (sanitize_text_field, absint, etc.) even where it is not a security bug; preferring WP APIs "
    "over direct database calls; no disallowed/discouraged functions; capability checks on admin actions; "
    "enqueuing scripts/styles rather than inlining. These are mostly Medium or Nit severity unless they cause "
    "a real bug. Report concrete violations naming the standard they break; do not invent style nits."
)

MINIMALISM_METHODOLOGY = (
    "MINIMALISM REVIEW — flag over-building: code that does more than the task "
    "needs. Look for: unrequested abstractions or configurability; a new "
    "dependency where the standard library or a native platform feature would "
    "do; a plugin where a hook or a small snippet would do; speculative, "
    "unused, or dead code; duplication that should reuse an existing helper. "
    "For each, name the simpler alternative concretely. Severities are mostly "
    "Nit or Medium unless the over-build causes a real bug. Do not flag a "
    "missing safety check, validation, sanitization, or test as over-build. "
    "That is the correctness and security reviewers' job and is the opposite "
    "concern. Do not invent nits where the structure is appropriate for the task."
)


def REVIEWER_PROMPT(diff: str, dimension: str, guidance_name: str, standards: str,
                    methodology: str = "") -> str:
    parts = [
        f"You are a meticulous {dimension} code reviewer. Review ONLY the change below.",
        f"First call read_guidance('{guidance_name}') and follow it as the standard. "
        "Use read_file and search_files to expand context (the enclosing function, "
        "callers, related code) before judging — a hunk in isolation hides bugs.",
    ]
    if methodology.strip():
        parts.append(methodology.strip())
    if standards.strip():
        parts.append("The user's saved standards/preferences (honor these):\n" + standards.strip())
    parts.append(REVIEW_OUTPUT_CONTRACT)
    parts.append("The change to review:\n" + diff)
    return "\n\n".join(parts)


def VERIFIER_PROMPT(finding: Finding, diff: str) -> str:
    loc = f"{finding.file}:{finding.line}" if finding.line is not None else finding.file
    return (
        "You are an adversarial verifier. A reviewer claims the following issue. Your "
        "job is to REFUTE it unless you can ground it concretely in the actual code. "
        "Use read_file and search_files to check. For a security issue, require a real "
        "source→sink path with no intervening guard; for a correctness issue, require a "
        "named broken caller or contract. Default to false-positive when uncertain.\n\n"
        f"Claimed issue: [{finding.severity}] {loc} — {finding.title}\n"
        f"Reviewer's evidence: {finding.evidence}\n\n"
        "Reply with exactly one of these on the first line:\n"
        "VERDICT: real\n"
        "VERDICT: false-positive\n"
        "then a 'grounding:' line explaining the concrete code path (or why it does not hold).\n\n"
        "Relevant change:\n" + diff
    )


def verifier_confirms(text: str) -> bool:
    """True only if the verifier explicitly returned VERDICT: real (fail-closed)."""
    for line in (text or "").splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("verdict:"):
            return stripped.split(":", 1)[1].strip() == "real"
    return False


_SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}  # Blocker=0 … Nit=3


def run_review(target, *, run_children, git_diff_fn, reviewers, standards="", verify_cap=16) -> str:
    diff = git_diff_fn(target)
    if not diff.strip() or diff.startswith(("Nothing to review", "Could not get a diff")):
        return diff if diff.strip() else "Nothing to review — the diff is empty."

    # Stage 1: fan out reviewers (read-only parallel children).
    reviewer_specs = []
    for r in reviewers:
        label, dimension, guidance = r[0], r[1], r[2]
        methodology = r[3] if len(r) > 3 else ""
        reviewer_specs.append({
            "prompt": REVIEWER_PROMPT(diff, dimension, guidance, standards, methodology),
            "role": None, "instructions": None, "label": label,
        })
    reviewer_reports = run_children(reviewer_specs)
    findings: list[Finding] = []
    for _label, report in reviewer_reports:
        if isinstance(report, str):
            findings.extend(parse_findings(report))
    if not findings:
        return synthesize([])

    # Stage 2: verify (severity-sorted, capped). The verify pass always runs.
    findings.sort(key=lambda f: _SEV_RANK.get(f.severity, 2))
    to_verify = findings[:verify_cap]
    verify_specs = [
        {"prompt": VERIFIER_PROMPT(f, diff), "role": None, "instructions": None,
         "label": f"verify:{f.file}"}
        for f in to_verify
    ]
    verdicts = run_children(verify_specs)
    # verdicts are positional (run_children returns submission order); a finding
    # is kept only if its verifier confirmed it. Do NOT use zip_longest — a short
    # verdicts list must drop the unmatched (fail-closed), not pad with None.
    kept = [
        f for f, (_label, verdict) in zip(to_verify, verdicts)
        if isinstance(verdict, str) and verifier_confirms(verdict)
    ]
    return synthesize(kept)
