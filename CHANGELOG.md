# Changelog

All notable changes to Heya are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Heya uses
[semantic versioning](https://semver.org/).

## [Unreleased]

### Added

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

[Unreleased]: https://github.com/shameemreza/heya/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/shameemreza/heya/releases/tag/v0.0.1
