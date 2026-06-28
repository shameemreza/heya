# The diagnostic workflow

This is Heya's specialty: take a WordPress or WooCommerce bug from a report to a
proven, paste-ready answer. It runs on a disposable WordPress Playground or a
development site you point it at. It never touches production, and it never posts
anything. You post.

## The shape

Heya runs four stages, each gated on evidence:

1. **Reproduce.** Turn the report into a structured spec, build a clean
   environment, and confirm the bug actually happens, code-level first, then the
   browser. No evidence, no verdict.
2. **Diagnose.** Classify the issue (a code bug, a config issue, a plugin or
   theme conflict, an environment or version problem, and so on), run the
   conflict test when it fits, and localize the likely cause. A fresh, skeptical
   verifier drops any claim it cannot ground.
3. **Remediate and verify.** Propose the right kind of fix (a setting, a snippet,
   a patch, a version bump), ground it against the installed source, apply it in
   the disposable environment, and prove it with a dual oracle: the original
   reproduction now passes and a regression check still passes.
4. **Deliver.** Aggregate everything into a triage report and a paste-ready
   comment carrying the decision bar, and write them to `repro/<slug>/`.

## Triage a single issue

Give Heya the report, a ticket reference, or a log:

```bash
.venv/bin/heya "triage WOO-1234: variation coupons apply to the parent price at checkout, WP 6.5, WC 8.7"
```

Heya intakes the issue (it can fetch a Linear or GitHub ticket through an MCP
server, gh, or the web), runs the stages, and writes:

- `repro/<slug>/triage-report.md` the full report.
- `repro/<slug>/triage-comment.md` the paste-ready comment.

### The decision bar

The comment is the product. Someone should be able to set a priority or close
the ticket from it without re-investigating. It carries:

- A plain-language opening: what the shopper or merchant experiences.
- The verdict and the versions tested.
- Impact: who is affected, under what conditions, the consequence, and any
  workaround.
- A suggested priority with one line of reasoning. Heya will not suggest "close"
  for an issue that still reproduces.
- The evidence and a one-click repro link.
- A suggested next step.

## Triage a backlog

Point Heya at a list of issues or a view. It ranks them from their text alone,
builds nothing yet, and writes a pick-list to `pick-list.md`, with one route per
issue: ready-to-fix, triage-first, needs-info, or skip. When you confirm which to
validate, it runs those through the single-issue flow, a few at a time.

## The hard rules

- No evidence, no verdict.
- Never post a comment, never change a ticket's status or labels. Heya writes the
  files; you post.
- Disposable or development environments only. Never production.
