---
name: environment
description: Check the environment before assuming it. Read the OS, shell, installed tools, and versions with commands rather than guessing, so an answer is not built on a wrong assumption. Override it with your own environment guidance.
---

# Environment

Do not assume the user's setup. Before an answer depends on the operating
system, an installed tool, a version, or a path, check it.

## Check, do not guess

- Operating system: `uname -a` on Linux and macOS, `sw_vers` for macOS details.
  On Windows the user is in a different shell; confirm rather than assume.
- The basics: which shell, the current directory, and what is on PATH.
- Tool versions, only the ones the task needs: `node --version`,
  `npm --version`, `php --version`, `python --version`, `wp --version`,
  `git --version`.
- For WordPress or WooCommerce work, confirm the site root and the WordPress,
  WooCommerce, and PHP versions rather than assuming them.

## When a tool is missing

If a command is not found, say so plainly and suggest how to install it. For
example, stdio MCP servers need Node.js, and `wp` is WP-CLI. Do not pretend a
command ran, and do not quietly switch to a guess.

## State what you observed

When the answer depends on the environment, name what you found, for example "on
macOS with Node 20 and PHP 8.2", so the user can correct you if their machine
differs. A wrong assumption stated as fact is worse than a quick check.
