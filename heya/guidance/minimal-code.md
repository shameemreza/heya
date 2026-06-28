---
name: minimal-code
description: Heya's default for writing and changing code. Prefer the smallest change that fully solves the problem. Climb the laziness ladder before you build, but never minimize safety. Override it with your own minimal-code guidance.
---

# Minimal code

The best code is the code you do not write. When you write or change code,
prefer the smallest change that fully solves the problem. This is a default; a
user can replace it with their own `minimal-code` guidance.

## Understand first

Climb the ladder after you understand the problem, not instead of it. Read the
task and the code it touches. Trace the real flow end to end. For a bug, find
the root cause, not the symptom: search every caller and fix the shared function
once rather than patching only the path that was reported.

## The ladder

Before writing code, stop at the first rung that holds:

1. Does this need to exist at all? If the task does not need it, do not build it.
2. Does it already exist in this codebase? Reuse the helper, util, or pattern.
3. Does the standard library already do this? Use it.
4. Does a native platform feature cover it? Use it. In a browser, an `<input
   type="date">` before a date-picker library. In WordPress, a core function or
   hook before custom code.
5. Does an already-installed dependency solve it? Use it before adding a new one.
6. Can this be one line? Make it one line.
7. Only then write minimal working code.

## In the WordPress and WooCommerce world

- Prefer a hook or filter (`add_filter`, `add_action`) or a small snippet over a
  whole new plugin.
- Prefer a core or WooCommerce function over a custom database query.
- Prefer an existing setting or template override over new code.
- A snippet or mu-plugin is a workaround, not a shipped fix. Say so when you
  offer one.

## Never minimize these

Be lazy about solutions, never about safety. These are not optional, and a
smaller change is never an excuse to drop them:

- Understanding the problem.
- Input validation and sanitization at trust boundaries.
- Error handling that prevents data loss.
- Security: escaping, capability and nonce checks, no injection.
- Accessibility.
- Anything the user explicitly asked for.

A change with non-trivial logic leaves one runnable check behind. Lazy code
without its check is unfinished.

## Say less, delete more

- No unrequested abstractions, dependencies, or boilerplate.
- Deletion over addition. Plain over clever. The fewest files that do the job.
- The shortest working diff wins, once you understand the problem.
- When a request sounds complex, ask what it actually needs before building to
  the full ask.

Adapted from the Ponytail project (MIT).
