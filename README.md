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

You need Python 3.13.

```bash
git clone git@github.com:shameemreza/heya.git
cd heya
python3.13 -m venv .venv
.venv/bin/pip install -e .
```

The browser tools are optional, since they pull in Playwright and a Chromium
binary. Add them when you want them:

```bash
.venv/bin/pip install -e ".[browser]"
.venv/bin/python -m playwright install chromium
```

Heya runs fine without them. The browser tools just return an install hint until
you do.

## Point it at a model

Copy the example config and edit it:

```bash
mkdir -p ~/.config/heya
cp config.example.toml ~/.config/heya/config.toml
```

For a local model with Ollama:

```bash
ollama pull qwen2.5-coder:14b
```

The default profile already points at `http://localhost:11434/v1`. For a cloud
model, add a profile with your endpoint and set the env var that holds your key.
See [docs/guide/getting-started.md](docs/guide/getting-started.md).

## Run it

```bash
.venv/bin/heya "summarize what changed in the last 3 commits"
```

Triage a bug end to end:

```bash
.venv/bin/heya "triage this: variation coupons apply to the parent price at checkout on WP 6.5 / WC 8.7"
```

Use a skill you already have:

```bash
.venv/bin/heya "use my support-reply skill to draft a response to this ticket: ..."
```

## Docs

- [Getting started](docs/guide/getting-started.md)
- [Configuration reference](docs/guide/configuration.md)
- [The diagnostic workflow](docs/guide/diagnostic-workflow.md)
- [Hosting your Claude skills, plugins, and tools](docs/guide/hosting-claude-ecosystem.md)
- [Tools and safety](docs/guide/tools-and-safety.md)

## License

MIT. See [LICENSE](LICENSE).
