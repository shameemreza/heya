"""Diagnosis-stage logic for the diagnostic workflow.

Pure helpers + the read-only fan-out/verify/synthesize orchestrator (Task 2).
Mirrors heya/review.py: deterministic, tolerant parsing, a fail-closed verify
gate, and a synthesis that says 'insufficient evidence' rather than fabricating.
No regex; nothing here raises into the agent loop (callers wrap)."""

from __future__ import annotations

from dataclasses import dataclass

ISSUE_CLASSES = (
    "bug", "config", "conflict", "environment", "user-error",
    "security", "integration", "performance", "caching", "client-side",
)

# Exact fatal/log substrings mapped to the class they most often indicate.
LOG_PATTERNS = (
    ("Allowed memory size", "environment"),
    ("Maximum execution time", "environment"),
    ("Cannot redeclare", "conflict"),
    ("Uncaught TypeError", "bug"),
    ("Uncaught Error: Class", "bug"),
    ('Class "', "bug"),
    ("dynamic property", "environment"),
    ("cURL error", "integration"),
    ("Out of memory", "environment"),
)

_CONFIDENCE = ("high", "medium", "low")


def classify_log(text: str) -> list[tuple[str, str]]:
    """Return (pattern, class) for each LOG_PATTERN substring present in `text`,
    in pattern order, deduped. Case-sensitive. Empty/no-match -> []."""
    hits: list[tuple[str, str]] = []
    seen = set()
    body = text or ""
    for pattern, cls in LOG_PATTERNS:
        if pattern in body and pattern not in seen:
            seen.add(pattern)
            hits.append((pattern, cls))
    return hits


def _frame_from_hash_line(s: str) -> tuple[str, int] | None:
    # "#0 /path/file.php(123): ..."
    if not s.startswith("#") or ".php(" not in s:
        return None
    head, _, rest = s.partition(".php(")
    slash = head.find("/")
    if slash == -1:
        return None
    file = head[slash:] + ".php"
    close = rest.find(")")
    if close == -1:
        return None
    digits = rest[:close].strip()
    if not digits.isdigit():
        return None
    return (file, int(digits))


def _frame_from_online(s: str) -> tuple[str, int] | None:
    # "... in /path/file.php on line 123" / "thrown in /path/file.php on line 123"
    if " on line " not in s or ".php" not in s:
        return None
    before, _, after = s.partition(" on line ")
    digits = ""
    for ch in after.strip():
        if ch.isdigit():
            digits += ch
        else:
            break
    if not digits:
        return None
    idx = before.rfind(".php")
    if idx == -1:
        return None
    end = idx + 4
    start = before.rfind(" ", 0, idx)
    file = before[start + 1:end] if start != -1 else before[:end]
    if not file.startswith("/"):
        slash = file.find("/")
        if slash == -1:
            return None
        file = file[slash:]
    return (file, int(digits))


def extract_trace_frames(text: str) -> list[tuple[str, int]]:
    """Parse PHP stack-trace / fatal lines into (file, line). No regex.
    Junk/empty -> []. Deduped, in first-seen order."""
    frames: list[tuple[str, int]] = []
    seen = set()
    for line in (text or "").splitlines():
        s = line.strip()
        frame = _frame_from_hash_line(s) or _frame_from_online(s)
        if frame is not None and frame not in seen:
            seen.add(frame)
            frames.append(frame)
    return frames


@dataclass(frozen=True)
class Hypothesis:
    issue_class: str
    claim: str
    evidence: tuple[str, ...]
    candidate_files: tuple[str, ...]
    confidence: str


def _norm_confidence(value: str) -> str:
    v = (value or "").strip().lower()
    return v if v in _CONFIDENCE else "low"


def _norm_class(value: str) -> str:
    v = (value or "").strip().lower()
    return v if v in ISSUE_CLASSES else "bug"


def _split_list(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    parts = [p.strip() for p in value.replace(";", ",").split(",")]
    return tuple(p for p in parts if p)


def _parse_block(block: str) -> Hypothesis | None:
    fields: dict[str, str] = {}
    for raw in block.splitlines():
        if ":" in raw:
            key, _, value = raw.partition(":")
            fields[key.strip().lower()] = value.strip()
    if not fields.get("claim"):
        return None  # a hypothesis needs at least a claim
    return Hypothesis(
        issue_class=_norm_class(fields.get("class", "")),
        claim=fields["claim"],
        evidence=_split_list(fields.get("evidence", "")),
        candidate_files=_split_list(fields.get("candidate_files", "")),
        confidence=_norm_confidence(fields.get("confidence", "")),
    )


def parse_hypotheses(text: str) -> list[Hypothesis]:
    """Parse `### HYPOTHESIS` … `### END` blocks; tolerant (skips malformed)."""
    out: list[Hypothesis] = []
    for chunk in (text or "").split("### HYPOTHESIS"):
        if "### END" not in chunk:
            continue
        block = chunk.split("### END", 1)[0]
        h = _parse_block(block)
        if h is not None:
            out.append(h)
    return out


def diagnosis_confirmed(text: str) -> bool:
    """True only if the verifier explicitly returned VERDICT: grounded (fail-closed)."""
    for line in (text or "").splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("verdict:"):
            return stripped.split(":", 1)[1].strip() == "grounded"
    return False


@dataclass(frozen=True)
class Diagnosis:
    issue_class: str
    confidence: str
    root_cause: str
    candidate_files: tuple[str, ...]
    evidence: tuple[str, ...]
    recommended_next_step: str
    alternatives: tuple[str, ...]


def _bullets(items) -> str:
    return "\n".join(f"- {x}" for x in items) if items else "- (none)"


def render_diagnosis(diag: Diagnosis) -> str:
    return (
        f"## Diagnosis\n\n"
        f"**Class:** {diag.issue_class} (confidence: {diag.confidence})\n\n"
        f"**Root cause (hypothesis):** {diag.root_cause}\n\n"
        f"**Candidate files:**\n{_bullets(diag.candidate_files)}\n\n"
        f"**Evidence:**\n{_bullets(diag.evidence)}\n\n"
        f"**Alternatives considered:** {', '.join(diag.alternatives) or '(none)'}\n\n"
        f"**Recommended next step:** {diag.recommended_next_step}\n"
    )


_CONF_RANK = {"high": 0, "medium": 1, "low": 2}


def synthesize_diagnosis(hypotheses) -> str:
    """Rank confirmed hypotheses (confidence, then evidence count) into one
    Diagnosis. No survivors -> an 'insufficient evidence' body, never fabricated."""
    if not hypotheses:
        diag = Diagnosis(
            issue_class="unknown", confidence="low",
            root_cause="insufficient evidence to localize a root cause",
            candidate_files=(), evidence=(),
            recommended_next_step="gather more evidence: read the relevant logs, "
            "run the conflict test, or reproduce the failing path at the code level",
            alternatives=(),
        )
        return render_diagnosis(diag)
    ranked = sorted(
        hypotheses,
        key=lambda h: (_CONF_RANK.get(h.confidence, 2), -len(h.evidence)),
    )
    primary = ranked[0]
    alternatives = tuple(
        h.issue_class for h in ranked[1:] if h.issue_class != primary.issue_class
    )
    evidence = tuple(dict.fromkeys(e for h in ranked for e in h.evidence))
    files = tuple(dict.fromkeys(f for h in ranked for f in h.candidate_files))
    diag = Diagnosis(
        issue_class=primary.issue_class, confidence=primary.confidence,
        root_cause=primary.claim, candidate_files=files, evidence=evidence,
        recommended_next_step=f"remediate ({primary.issue_class}): see 12c",
        alternatives=alternatives,
    )
    return render_diagnosis(diag)


# (label, lens-instruction) — one read-only explorer per lens. The label names
# the class the lens probes; the instruction tells the explorer what to test.
DIAGNOSIS_LENSES = (
    ("conflict", "Test whether a plugin or theme conflict explains the symptom "
     "(the conflict test result, redeclared functions, overrides)."),
    ("config", "Test whether a setting or configuration explains it (compare the "
     "actual settings against what the expected behavior requires)."),
    ("environment", "Test whether the environment explains it (PHP/WP/WC version "
     "floors, memory or execution limits, missing extensions)."),
    ("bug", "Test whether this is a genuine code bug, and if so localize it: which "
     "installed source file and function. Use the stack trace and search_files."),
    ("integration", "Test whether a third-party integration explains it (gateway, "
     "shipping, tax, email): credentials, connectivity, API errors in the log."),
    ("other", "Test the remaining classes (security, performance, caching, "
     "client-side, user-error) and report the best-supported one, if any."),
)

_HYPOTHESIS_CONTRACT = (
    "Return zero or more hypotheses. For each, emit exactly this block:\n"
    "### HYPOTHESIS\n"
    "class: <one of: " + ", ".join(ISSUE_CLASSES) + ">\n"
    "claim: <one sentence root-cause claim>\n"
    "evidence: <comma-separated artifacts you actually observed: log lines, file:line, "
    "command output; NEVER your own assertion>\n"
    "candidate_files: <comma-separated installed-source paths, if any>\n"
    "confidence: <high|medium|low>\n"
    "### END\n"
    "Ground every claim in a captured artifact or the installed source. If you "
    "cannot ground a lens, emit no block for it."
)


def HYPOTHESIS_PROMPT(context: str, evidence: str, lens: str) -> str:
    return (
        "You are a diagnostic investigator. First call read_guidance('diagnosis') "
        "and follow it. Use read_file and search_files to check the installed source; "
        "do not assert a cause you cannot ground in an artifact.\n\n"
        f"Lens for this pass: {lens}\n\n"
        f"Issue context:\n{context}\n\n"
        f"Evidence gathered so far:\n{evidence}\n\n"
        + _HYPOTHESIS_CONTRACT
    )


def VERIFY_HYPOTHESIS_PROMPT(hyp: "Hypothesis", context: str, evidence: str) -> str:
    return (
        "You are an adversarial verifier. A diagnostic investigator claims the "
        "hypothesis below. Try to REFUTE it. It is 'grounded' ONLY if every part of "
        "the claim is backed by a concrete artifact you can confirm (a log line, a "
        "file:line in the installed source, command output). Use read_file and "
        "search_files to check. Default to ungrounded when uncertain.\n\n"
        f"Claimed class: {hyp.issue_class}\n"
        f"Claim: {hyp.claim}\n"
        f"Investigator's evidence: {', '.join(hyp.evidence) or '(none)'}\n"
        f"Candidate files: {', '.join(hyp.candidate_files) or '(none)'}\n\n"
        f"Issue context:\n{context}\n\nEvidence:\n{evidence}\n\n"
        "Reply with exactly one of these on the first line:\n"
        "VERDICT: grounded\n"
        "VERDICT: ungrounded\n"
        "then a 'grounding:' line explaining the concrete artifact (or why it does not hold)."
    )


def run_diagnosis(context, evidence, *, run_children, lenses=DIAGNOSIS_LENSES, verify_cap=16) -> str:
    """Read-only fan-out -> fail-closed adversarial verify -> synthesize. Mirrors
    run_review. `run_children(specs)` returns submission-ordered [(label, report)].
    Never raises (callers wrap)."""
    # Stage 1: one explorer per lens.
    explorer_specs = [
        {"prompt": HYPOTHESIS_PROMPT(context, evidence, instruction),
         "role": None, "instructions": None, "label": f"diagnose:{label}"}
        for label, instruction in lenses
    ]
    reports = run_children(explorer_specs)
    hypotheses: list[Hypothesis] = []
    for _label, report in reports:
        if isinstance(report, str):
            hypotheses.extend(parse_hypotheses(report))
    if not hypotheses:
        return synthesize_diagnosis([])

    # Stage 2: adversarially verify (capped). Fail-closed: keep only grounded.
    ranked = sorted(hypotheses, key=lambda h: _CONF_RANK.get(h.confidence, 2))
    to_verify = ranked[:verify_cap]
    verify_specs = [
        {"prompt": VERIFY_HYPOTHESIS_PROMPT(h, context, evidence),
         "role": None, "instructions": None, "label": f"verify:{h.issue_class}"}
        for h in to_verify
    ]
    verdicts = run_children(verify_specs)
    kept = [
        h for h, (_label, verdict) in zip(to_verify, verdicts)
        if isinstance(verdict, str) and diagnosis_confirmed(verdict)
    ]
    return synthesize_diagnosis(kept)
