---
name: code-review
description: Baseline checklist for reviewing a code change.
---

# Code review

Review the change, not the whole file. Focus on what this diff adds.

- Correctness: does it do what it claims? Walk the main path and one edge case.
- Tests: is the new behavior covered by a test that would fail without the change?
- Failure modes: errors, empty input, timeouts, partial failure — handled or surfaced?
- Security: untrusted input validated; no secrets in code; least privilege.
- Readability: clear names, one responsibility per unit, no dead code.
- Scope: nothing built that wasn't needed; nothing half-built left behind.

Say plainly whether it's ready. If not, name the specific thing to fix.

For over-building (unneeded abstractions, a library where the standard library or a native feature works, a plugin where a snippet works), also consult `read_guidance('minimal-code')`.
