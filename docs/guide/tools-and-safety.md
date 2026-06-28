# Tools and safety

Heya runs one streaming function-calling loop. The model asks for a tool, Heya
runs it, and the result goes back into the loop. The safety model is simple and
visible.

## What runs without asking, and what asks first

Reads run on their own. Anything that changes the world asks first.

- Runs on its own: `read_file`, `search_files`, `read_guidance`, `read_log`,
  `web_search`, `web_fetch`, browser reads, memory reads.
- Asks first: `write_file`, `run_command`, `run_wp_cli`, and browser clicks and
  typing.

Approve a prompted action once, approve it for the session, or decline it. With
`--auto-approve`, the prompted tools run without asking. Use that only in a
sandbox you trust.

## The allow-list

The file and command tools are confined to an allow-list of folders. The current
directory is always allowed; add more with `--allow DIR` or the `[workspace]`
config. A path that escapes the allow-list is rejected. Commands always carry a
timeout.

## The tools

- **Files and shell:** `read_file`, `write_file`, `search_files`, `run_command`,
  `check_command`, `kill_command`.
- **Guidance:** `read_guidance` reads internal guidance, a bundled baseline plus
  your own folders, so answers follow your standards and voice.
- **Web:** `web_search` and `web_fetch` (a page returned as readable text).
- **Browser:** a real headless Chromium through Playwright. Navigate, click,
  type, screenshot, and pull console and network errors to reproduce a bug.
- **WordPress:** `read_log`, `run_wp_cli`, and `wp_playground` to boot a disposable
  WordPress for a clean-room reproduction.
- **Sub-agents:** `spawn_agent` for a single delegated task, `spawn_agents` to fan
  read-only children out in parallel.
- **Memory:** `remember`, `update_memory`, `forget`, `read_memory`.
- **Code review:** `review_changes`.
- **Diagnostics:** the reproduce, diagnose, remediate, and triage tools described
  in [the diagnostic workflow](diagnostic-workflow.md).
- **Skills:** `Skill` to load one of your installed skills.
- **MCP:** any tools exposed by the Model Context Protocol servers you connect.

## How tools behave

Tools never raise into the agent loop. On a problem they return a short
`Error: ...` string, so a single failing tool never crashes a task. Long tool
output is truncated with an explicit marker, never a silent cut.

## Sub-agents

A sub-agent is a fresh agent with its own context. It sees only the task you give
it, not your conversation. Parallel sub-agents are read-only by design: they get
the read-only tool surface and the shared browser and WordPress sessions are
withheld, so several can run at once with no races.

## Privacy

Heya is local-first. With a local model, nothing leaves your machine. With a
cloud model, only what you send to that model's API leaves. API keys are read
from environment variables you name in config; Heya never stores a key.
