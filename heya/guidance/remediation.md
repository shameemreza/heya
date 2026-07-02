---
name: remediation
description: Methodology for proposing and verifying a fix after diagnosis. Covers fix forms by issue class, grounding requirements, and the bounded repair loop.
---

# Remediation methodology

Use this after a diagnosis to propose a fix and prove it works. You apply fixes
only in the disposable environment, never on a production site. You produce a
solution writeup; you do not post anywhere.

## Choose the fix form by class

- config: change the setting (or wp option). No code.
- user-error or how-to: explain, link the doc. No code.
- conflict: deconflict by a setting or a small snippet, or recommend an
  alternative plugin, and report it to that plugin's author.
- bug: a code patch upstream, with a snippet or mu-plugin as an interim
  workaround.
- environment: a version bump or rollback, or a server or host change.
- integration: fix the credentials or connectivity.
- security: do not patch. Isolate, rotate credentials, scan, restore.

A snippet or mu-plugin is an unsupported workaround, not a supported fix. Label
it as such, and point merchants to a partner for supported customization. Never
edit core or plugin files in place; use hooks, a child theme, or a snippet.

## Cite or do not recommend

Every hook, function, option, or class your fix uses must exist in the installed
source and must not be deprecated for that version. Confirm it with read_file
and search_files before you propose it. If you cannot ground a symbol, do not
use it. The grounding check (check_remediation) enforces this and refuses an
ungrounded fix.

Two traps that make a plausible fix wrong:
- HPOS: order data is not in wp_posts or wp_postmeta. Use CRUD: wc_get_order,
  then get_meta, get_total, get_items.
- Block checkout: most classic checkout hooks do nothing on the React or Store
  API checkout.

## Make the oracle first

Before you trust a fix, confirm the reproduction check actually fails on the
broken environment. A check that passes on the broken site proves nothing. That
failing check is your evidence target: the fix must turn it from fail to pass.

## Prove the fix with a dual oracle, every attempt

A fix is verified only when both hold on a fresh disposable environment:
- the original reproduction now passes, and
- a regression smoke set still passes: the key pages load, no new PHP fatals or
  warnings appear in the log, and cart and checkout still work.

record_fix_verdict enforces this. A claim without both oracles and evidence is
recorded as not-verified. Do not call a fix done on one passing test alone; a
weak check hides a fix that broke something else.

## The repair loop, bounded

1. Propose a fix.
2. check_remediation: ground it and check edit safety. Run php -l on PHP.
3. Apply it in the disposable environment.
4. Re-run the reproduction and the regression smoke set, capturing evidence.
5. record_fix_verdict. Verified means done.
6. If not verified, feed the raw failure output back, avoid any patch you already
   tried, and refine. Stop after three attempts (four at the very most), or
   sooner if you are repeating a patch or seeing the same failure twice. More
   attempts past that tend to make things worse, not better.

Write the solution either way: the verified fix with its evidence, or the best
attempt with an honest not-verified note and what is still failing.

When the fix involves writing code, also follow `read_guidance('minimal-code')`: prefer the smallest change that fully solves the problem, and never minimize validation or security.
