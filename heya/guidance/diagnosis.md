# Diagnosis methodology

Use this after an issue is reproduced (or when a log points at it) to decide what
class of issue it is, where the root cause lives, and what to fix next. Ground
every conclusion in an artifact. Never assert a cause you cannot show.

## Classify in two steps

First the request type: bug, config, how-to, change-request, or security. A
how-to or change-request is not a defect; answer it as guidance, do not hunt for
a bug. Then, for a defect, the cause class:

- bug: genuine code defect, reproduces on a clean install.
- config: a setting is wrong or missing.
- conflict: another plugin or the theme causes it.
- environment: PHP, WP, or WC version, memory or execution limits, missing
  extension, host.
- user-error: the steps or expectation are mistaken.
- security: malware, compromise, leaked credentials. Different playbook: isolate,
  rotate credentials, scan, restore. Do not treat as an ordinary bug.
- integration: a third-party service (gateway, shipping, tax, email) fails,
  usually credentials or connectivity.
- performance: slow queries, heavy autoloaded options, scaling.
- caching: a caching layer serving stale cart, checkout, or nonce data.
- client-side: JavaScript or AJAX failure, often invisible in the PHP log.

Intermittent is an attribute, not a class. Note it and keep going.

## The conflict test (the highest-yield first move)

Roughly half of support issues are third-party conflicts, so run this early when
a conflict is plausible.

1. Back up first.
2. Switch to a default theme (for example Twenty Twenty-Five) or Storefront, and
   retest. If it stops, it is theme-related.
3. Deactivate every plugin except WooCommerce and the named extension, and retest.
   If it stops, a plugin is the cause.
4. Reactivate the others one by one, or by half-split for speed, retesting each
   time, until the culprit reappears.

Do this on the disposable Playground site or an explicitly provided development
site. Never on production.

## Localize the code (when it is a bug)

Localization is the hard part, so be deliberate. In order:

1. Stack trace first. The fatal line and the trace frames name the file and line.
   This is the single strongest signal.
2. Grep shortlist. Use search_files for the function, hook, or message involved,
   scoped to the installed plugin, to get a small candidate set.
3. Narrow. Read only those candidates and the enclosing function. Do not read a
   whole plugin looking for the cause.

## Cite or drop

Every claim in a diagnosis must point to an artifact: a log line, a file and
line in the installed source, or command output. If you cannot ground a claim,
drop it. A confident guess is worse than "insufficient evidence", because a
wrong root cause sends the fix in the wrong direction. The verifier enforces
this: a hypothesis it cannot ground is dropped.

## Two WooCommerce traps that mislead diagnosis

- HPOS: order data is not in wp_posts or wp_postmeta. get_post_meta on an order
  returns stale or empty data. Read with CRUD: wc_get_order, then get_meta,
  get_total, get_items.
- Block checkout: most classic checkout hooks (woocommerce_checkout_fields,
  woocommerce_review_order_*) do nothing on the React or Store API checkout.
  Code that looks correct can be inert there.

## Log signals

- "Allowed memory size ..." or "Maximum execution time ...": environment.
- "Cannot redeclare ...": conflict or double-include.
- "Uncaught TypeError": version or compatibility.
- 'Class "X" not found': missing dependency or autoload.
- "cURL error": integration or connectivity.
- "Creation of dynamic property ... is deprecated": PHP 8.2+ compat notice.
- A white screen with no error: a fatal with display off. Enable WP_DEBUG_LOG.

WooCommerce logs are under wp-content/uploads/wc-logs/; the debug log is
wp-content/debug.log when WP_DEBUG and WP_DEBUG_LOG are on.

## Escalation when the evidence is thin

When diagnose_issue returns "insufficient evidence to localize," do not fabricate
a cause and do not give up. Gather exactly one more signal, then call
diagnose_issue again:

- Enable WP_DEBUG_LOG and re-read the log.
- Run a wp diagnostic you have not run yet (wp plugin list, wp option get, a
  wp wc command, wp db check).
- Widen or repeat the conflict test.

After two escalation rounds with still no grounded hypothesis, stop and report it
blocked as insufficient evidence, with what you tried and what is still missing.
A bounded counter enforces this: diagnose_issue tells you when you have reached
the limit. Guessing a wrong root cause is worse than an honest "insufficient
evidence," because it sends the fix in the wrong direction.
