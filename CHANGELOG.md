# Changelog

All notable changes to Heya are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Heya uses
[semantic versioning](https://semver.org/).

## [Unreleased]

## [0.0.3] - 2026-07-02

A hardening release: the CLI no longer crashes on ordinary network or
filesystem failures, several security holes are closed, and the packaging and
documentation bugs from 0.0.2 are fixed. Nothing here blocks access to a real
site, local or live.

### Security

- `web_fetch` and `browser_navigate` now block cloud-metadata and link-local
  addresses (such as `169.254.169.254`) by default, and re-check the host on
  every redirect hop. Loopback, private, and public addresses are all allowed,
  so local dev sites and live customer sites are unaffected. Set
  `block_metadata = false` under `[web]` to turn it off.
- The approval allow-list no longer auto-approves a command that contains shell
  metacharacters, so a whitelisted prefix like `git status` can no longer carry
  a chained `; curl … | sh`. Matching is now on argv token boundaries.
- Interactive "always" is scoped to the specific command for `run_command` and
  `run_wp_cli`, so approving one command no longer silently approves every later
  shell command.
- `run_wp_cli` runs argv-style, so its arguments can no longer chain arbitrary
  shell commands.
- The system prompt now frames text returned by the web, the browser, logs, MCP
  tools, and files as data, not instructions.
- The background-agent launch approval now states plainly that a command grant
  runs a full shell that is not confined to the leased folder.

### Fixed

- Transient model errors (HTTP 429 and 5xx, connection and read timeouts) are
  retried with backoff, honoring `Retry-After`. A malformed streaming chunk is
  skipped instead of ending the turn.
- An error during a turn now keeps the interactive session alive with a short
  message instead of exiting with a traceback; the one-shot path returns a
  non-zero exit code. `Ctrl+C` interrupts the current turn and returns to the
  prompt rather than killing the process.
- The tool boundary never raises into the loop: filesystem errors (permission
  denied, out of space) and unexpected tool failures come back as a readable
  error string.
- `keyring` is declared under the `mcp` extra, so MCP OAuth token persistence
  works after `pip install "heya-agent[mcp]"`.
- The bundled guidance references to `avoid-regex` and `sentence-case-ui` now
  resolve; both files ship.
- Corrected documentation: the `CONTRIBUTING` install extra, the key-storage
  description in the tools-and-safety guide, and the setup instructions that
  pointed installed users at a file not included in the wheel.

### Changed

- A status indicator shows while a tool runs, so long operations are not silent.
- Added a `ruff` lint job to CI and cleaned the codebase to pass it; dropped the
  drifted `requirements.txt` files in favor of the packaging extras.
- Refreshed the README with the current features, badges, and links to every
  guide, and documented the MCP OAuth settings, the `[approval]` allow-list, the
  per-profile `vision` key, and the new `[web] block_metadata` setting.

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

[Unreleased]: https://github.com/shameemreza/heya/compare/v0.0.3...HEAD
[0.0.3]: https://github.com/shameemreza/heya/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/shameemreza/heya/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/shameemreza/heya/releases/tag/v0.0.1
