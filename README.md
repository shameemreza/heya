# Heya

Heya is a single, local-first AI agent that runs in your terminal. One model,
one agent, a toolbox. It reads a request, decides what to do, calls tools, and
loops until the task is done.

The model is a configuration choice, not part of the design. The same loop runs
against a small local model through Ollama or a frontier cloud model through
OpenRouter, OpenAI, LM Studio, or anything that speaks the OpenAI chat API. Point
it at whatever you have. Your prompts and your data stay on your machine.

It is built in plain Python with no agent framework, so you can see exactly what
every part does.

## Why you might use it

Most agents are general. Heya is general too, but it carries a real specialty: a
WordPress and WooCommerce diagnostic assistant that takes a bug from a ticket to
a proven answer. And because it is model-agnostic and local-first, you run all of
that on your own models, with no vendor lock-in and nothing leaving your machine.

It also hosts the Claude Code ecosystem. Your existing Claude skills, plugins,
hooks, commands, and sub-agents work in Heya with no re-install, so you bring
what you already have.

## What it can do

- **Diagnostic assistant.** Give Heya a bug report, a ticket, or a log. It
  reproduces the issue on a disposable WordPress Playground (or a dev site),
  finds the root cause, proposes and verifies a fix, and hands you a paste-ready
  triage comment with a verdict, impact, suggested priority, evidence, and a
  one-click repro link. Every stage is evidence-gated: no evidence, no verdict.
  It can also rank a backlog into a pick-list so you know what to work on.
- **Hosts your Claude ecosystem.** Discovers your `~/.claude` skills and plugins
  and makes them available through a `Skill` tool, runs lifecycle hooks (off by
  default), and turns Claude sub-agent and command definitions into Heya roles
  and commands.
- **Sub-agents.** Delegate a self-contained task to a fresh, context-isolated
  child agent, or fan several read-only children out in parallel and synthesize
  their reports.
- **MCP client.** Connect Model Context Protocol servers over stdio or HTTP, with
  OAuth, sampling, elicitation, and logging.
- **Memory.** Heya remembers facts across sessions in plain markdown files you
  can read and edit.
- **Code review.** A deterministic gather, fan-out, adversarially-verify,
  synthesize pipeline that reports real issues and says "nothing blocks" rather
  than inventing findings.
- **Cost and context controls.** An optional cheaper model for forgiving work,
  a per-task token budget, and context compaction so long sessions keep working
  on small-window local models.
- **Files, shell, web, and a real browser.** All writes, shell commands, and
  browser clicks ask before they run. Reads run on their own. Everything is
  confined to an allow-list of folders.

## Install

You need Python 3.11 or newer. The package is `heya-agent`; the command is
`heya`.

```bash
pipx install heya-agent
```

[pipx](https://pipx.pypa.io) installs it into its own isolated environment and
puts `heya` on your PATH. If you do not have pipx, `pip install heya-agent`
works too. Then run `heya init` to set up a model.

The browser tools are optional, since they pull in Playwright and a Chromium
binary. Add them when you want them:

```bash
pipx install "heya-agent[browser]"
python -m playwright install chromium
```

Heya runs fine without them. The browser tools just return an install hint until
you do.

### From source (for contributors)

```bash
git clone git@github.com:shameemreza/heya.git
cd heya
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest
```

## Point it at a model

Run the setup wizard. It walks you through a local (Ollama) or cloud model and
writes the config for you:

```bash
heya init
```

A pasted cloud key is stored in a locked credentials file, never in the config.
On the local path the wizard offers to download a model for you. If you would
rather configure by hand, copy `config.example.toml` to
`~/.config/heya/config.toml` and edit it. See
[docs/guide/getting-started.md](docs/guide/getting-started.md).

## Run it

```bash
heya "summarize what changed in the last 3 commits"
```

Triage a bug end to end:

```bash
heya "triage this: variation coupons apply to the parent price at checkout on WP 6.5 / WC 8.7"
```

Use a skill you already have:

```bash
heya "use my support-reply skill to draft a response to this ticket: ..."
```

## Docs

- [Getting started](docs/guide/getting-started.md)
- [Configuration reference](docs/guide/configuration.md)
- [The diagnostic workflow](docs/guide/diagnostic-workflow.md)
- [Hosting your Claude skills, plugins, and tools](docs/guide/hosting-claude-ecosystem.md)
- [Tools and safety](docs/guide/tools-and-safety.md)

## License

MIT. See [LICENSE](LICENSE).
