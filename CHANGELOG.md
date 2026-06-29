# Changelog

All notable changes to Heya are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Heya uses
[semantic versioning](https://semver.org/).

## [Unreleased]

## [0.0.2] - 2026-06-29

### Added

- Connect a development or staging WordPress and WooCommerce site with
  `heya wp connect`, then act on it through the official Abilities API: discover
  and run abilities (query orders, update status, manage products) under the
  site's own permission checks, with writes behind the approval prompt. Plus
  guidance for making your own plugin AI-callable.
- A `heya update` command that upgrades Heya in place (pipx or pip), and an
  optional startup notice when a newer version is on PyPI. The check is
  throttled, off the main thread, silent when offline, and disabled with
  `[update] check = false`.
- Background agents: launch sub-agents that run in the background while you keep
  working, for parallel audits, research, and building plugins or themes. They
  can write and run commands within a folder they lease exclusively, authorized
  once at launch, so concurrent agents never collide.
- WordPress development guidance, so Heya writes secure, standards-compliant
  plugins, themes, and code snippets that are ready for WordPress.org review.
  It activates automatically on WordPress work and routes across security,
  structure, coding standards and i18n, readme and naming, themes, blocks, and
  WooCommerce.
- Read a project's `AGENTS.md` and `CLAUDE.md` as context, so Heya picks up the
  conventions of the repo you run it in. Text only, never run, and it does not
  override Heya's safety rules. Disable with `[project] read_instructions = false`.

### Fixed

- Write the credentials file at mode 0o600 atomically, closing a brief window
  where it could be world-readable between the write and the chmod.
- `/resume` no longer matches a glued token like `/resumeabc`, and a bare
  `/resume` resumes the most recent session, matching `--resume`.
- `/model` says "no profiles loaded" instead of printing an empty list.

## [0.0.1] - 2026-06-28

First public release.

### Added

- A local-first, model-agnostic, tool-using agent with a `heya` command,
  one-shot (`heya "task"`) and interactive modes.
- `heya init` setup wizard: pick a local (Ollama) or cloud model, with the key
  stored in a locked credentials file, never in the config.
- A startup model preflight that shows a calm hint instead of a traceback when
  no model is ready.
- ASCII-art startup banner, slash commands, live tool trace, and colored
  approval diffs.
- A diagnostic workflow for support work: reproduce, diagnose, remediate, and a
  triage deliverable.
- Hosting for Claude-format skills, plugins, commands, sub-agents, and hooks.
- Bundled default guidance (writing voice, banned words, support replies) that
  can be overridden.

[Unreleased]: https://github.com/shameemreza/heya/compare/v0.0.2...HEAD
[0.0.2]: https://github.com/shameemreza/heya/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/shameemreza/heya/releases/tag/v0.0.1
