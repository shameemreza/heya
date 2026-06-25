---
name: reproduction
description: Methodology for reproducing and classifying reported issues.
---

# Reproduction methodology

Use this when a user gives you a bug report, a ticket, a log, or a "this is
broken" and wants it reproduced. Goal: prove whether the issue happens, with
evidence, and end in one verdict. You produce files and a paste-ready comment.
You never post anything or change a ticket's state. The human posts.

## Hard rules

- No evidence, no verdict. A verdict other than "blocked" needs at least one
  captured artifact: a screenshot path, a log excerpt, an assertion output, or
  a failed-network entry. Your claim is never the evidence.
- Code reading alone never decides a verdict. It can point at a cause; only a
  live test confirms one.
- Never post comments, never change status or labels. Produce report.md and
  comment.md; tell the user where they are.

## Intake

Parse the report into structured fields and call start_reproduction with them:
steps, expected, actual, and a version context (wp/wc/php). If steps, expected,
actual, or any version are missing, start_reproduction returns a needs-info
"blocked" result and builds no environment. That needs-info list is useful
output on its own. Read attached context (logs, screenshots) before deciding
fields are missing.

## The funnel, in order, stop at the first stage that clears the issue

1. Update everything to current stable, retest.
2. Theme test: switch to a default theme (for example Twenty Twenty-Five) or
   Storefront. If the issue stops, it is theme-related.
3. Plugin test: deactivate everything except WooCommerce and the named
   extension. If the issue stops, reactivate one by one (or half-split) to find
   the culprit. A conflict that stops here is the finding.
4. Clean-room reproduction: reproduce on a fresh WordPress Playground install
   with only the relevant plugins. If it reproduces here, it is a genuine
   core or extension bug, not a conflict or local config.
5. Escalate: if it persists in core, the report is the evidence to hand off.

Each stage that clears the issue localizes its class. Stop at the first one.

## Two reproduction layers, in order

- Code level first. wp-cli, REST or Store API calls, or a small PHP assertion
  run inside the test site. Cheap and fast; many backend bugs (totals, tax,
  HPOS, hooks) resolve here. Do not open a browser until this layer cannot
  decide.
- Browser level second. Drive the reporter's steps with the browser tools,
  capturing a screenshot at each step. This validates "I see X on screen" bugs.
  Retry a flaky step once; persistent flakiness is "blocked" with the flake
  noted, never a silent pass.

Save every artifact under repro/<slug>/evidence/.

## Log patterns and what they suggest

- "Allowed memory size of N bytes exhausted" -> environment or memory limit.
- "Maximum execution time of N seconds exceeded" -> slow query, import, or hung
  external call.
- "Cannot redeclare <function>" -> conflict or double-include (often a missing
  function_exists guard).
- "Uncaught TypeError" -> version or compatibility (old code on a newer PHP).
- 'Uncaught Error: Class "X" not found' -> missing dependency plugin or
  autoloader not loaded.
- "Creation of dynamic property ... is deprecated" -> PHP 8.2+ compat notice,
  not breakage.
- A white screen with no error -> a fatal with display off. Enable WP_DEBUG_LOG
  to surface the real fatal, then read the log.

WooCommerce logs live under wp-content/uploads/wc-logs/; the WordPress debug log
is wp-content/debug.log when WP_DEBUG and WP_DEBUG_LOG are on.

## Verdicts

End in exactly one:

- reproduced: confirmed on current stable WP and WC.
- fixed-since-report: fails on the reported version, passes on latest. Run both
  legs when versions allow; this verdict needs the two-leg evidence.
- cannot-reproduce: followed the steps on the tested versions, behavior matches
  expected. Return to the reporter with the environment so they can show what
  differs.
- blocked: missing info, or an environment the tool cannot build. State exactly
  what is missing.

Call record_repro_verdict with the verdict and the artifacts you captured. If a
non-blocked verdict has no evidence, the gate downgrades it to blocked. That is
intended: get the evidence or say blocked.

## Output

record_repro_verdict writes report.md and comment.md into repro/<slug>/. Write
the comment like a person: short sentences, facts first, no em dashes, no emoji,
no stacked hedging. Then tell the user where the files are. Do not post them.
