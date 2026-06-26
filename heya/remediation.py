"""Remediation-stage logic for the diagnostic workflow.

The repair loop itself is stateful and agent-driven (apply a fix to the
disposable env, re-run the repro). This module provides the deterministic gates:
edit-safety, the dual-oracle fix-verified gate, the bounded no-progress stop,
the fail-closed grounding gate, and the solution writeup. Plus the read-only
grounding orchestrator (Task 2). No regex; nothing here raises (callers wrap).
Mirrors heya/review.py and heya/diagnosis.py."""

from __future__ import annotations

import json

FIX_KINDS = ("setting", "snippet", "mu-plugin", "patch", "version")

# issue class -> appropriate remediation form(s). Guidance, not enforcement.
REMEDIATION_FORMS = {
    "config": ("setting",),
    "conflict": ("setting", "snippet", "escalate"),
    "bug": ("patch", "snippet"),
    "environment": ("version", "host"),
    "integration": ("setting", "credentials"),
    "user-error": ("guidance",),
    "security": ("incident",),
    "performance": ("setting", "patch"),
    "caching": ("setting",),
    "client-side": ("patch",),
}


def check_fix_safety(kind: str, content: str) -> tuple[bool, str]:
    """Deterministic pre-apply check. JSON validity for a setting; a lightweight
    PHP sanity check for code kinds. Never raises."""
    body = content or ""
    if kind == "setting":
        try:
            json.loads(body)
        except (ValueError, TypeError) as exc:
            return (False, f"setting is not valid JSON: {exc}")
        return (True, "valid JSON setting")
    if kind in ("snippet", "mu-plugin", "patch"):
        if not body.strip():
            return (False, "empty fix content")
        if body.count("{") != body.count("}"):
            return (False, "unbalanced braces")
        if body.count("(") != body.count(")"):
            return (False, "unbalanced parentheses")
        if kind in ("snippet", "mu-plugin") and "<?php" not in body and "<?" not in body:
            return (False, "PHP file is missing an opening <?php tag")
        return (True, "passed basic PHP sanity; run php -l to confirm")
    if kind == "version":
        if not body.strip():
            return (False, "version target is empty")
        return (True, "version change")
    return (False, f"unknown fix kind {kind!r}")


def gate_fix_verdict(*, repro_passes, regression_passes, evidence) -> str:
    """Fail-closed dual oracle: 'verified' only when the original repro now passes
    AND the regression set still passes AND evidence backs it. Else 'not-verified'.
    The execution oracle is the sole authority; there is no LLM vote here."""
    if repro_passes and regression_passes and evidence:
        return "verified"
    return "not-verified"


def _normalize(text: str) -> str:
    return " ".join((text or "").split())


def repair_should_stop(attempts, candidate, *, cap: int = 3) -> tuple[bool, str]:
    """Bound + no-progress detector for the agent's repair loop. `attempts` is a
    list of dicts: {'patch': str, 'signature': str, 'verified': bool?}."""
    items = list(attempts or [])
    if any(a.get("verified") for a in items):
        return (True, "a prior attempt was already verified")
    if len(items) >= cap:
        return (True, f"reached the attempt cap ({cap})")
    norm = _normalize(candidate)
    if norm and any(_normalize(a.get("patch", "")) == norm for a in items):
        return (True, "candidate is identical to a rejected attempt")
    sigs = [a.get("signature", "") for a in items if a.get("signature")]
    if len(sigs) >= 2 and sigs[-1] == sigs[-2]:
        return (True, "the same failure signature repeated")
    return (False, "")


def fix_grounded(text: str) -> bool:
    """True only if the verifier explicitly returned VERDICT: grounded (fail-closed)."""
    for line in (text or "").splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("verdict:"):
            return stripped.split(":", 1)[1].strip() == "grounded"
    return False


def _bullets(items) -> str:
    return "\n".join(f"- {x}" for x in items) if items else "- (none)"


def render_solution(ctx, *, kind, content, verdict, evidence,
                    how_to_apply, caveats) -> str:
    workaround = kind in ("snippet", "mu-plugin")
    kind_line = f"**Fix kind:** {kind}" + ("  (unsupported workaround)" if workaround else "")
    return (
        f"## Solution: {ctx.source or '(no source)'}\n\n"
        f"**Verdict:** {verdict}\n\n"
        f"{kind_line}\n\n"
        f"**How to apply:**\n{how_to_apply}\n\n"
        f"**The fix:**\n```\n{content}\n```\n\n"
        f"**Evidence it works:**\n{_bullets(evidence)}\n\n"
        f"**Caveats:** {caveats or '(none)'}\n"
    )
