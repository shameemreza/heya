# Heya

Heya is a single, local-first AI agent that runs in your terminal. One model, one agent, a toolbox. It reads a request, decides what to do, calls tools, and loops until the task is done.

The model is a configuration choice, not part of the design. The same loop runs against a small local model through Ollama or a frontier cloud model through OpenAI, OpenRouter, or anything that speaks the OpenAI chat API. Point it at whatever you have.

I'm building it in plain Python with no agent framework, so I can see exactly what every part does.

## What it can do

Heya has a small set of tools on one streaming function-calling loop:

- **Files and shell:** `read_file`, `write_file`, and `run_command`, all confined to an allow-list of folders with a required timeout on commands.
- **Guidance:** `read_guidance` reads internal guidance, a bundled baseline plus your own folders, so answers follow your standards and voice.
- **Web:** `web_search` (DuckDuckGo by default, or Brave/Tavily with your own key) and `web_fetch` (a page returned as readable text).
- **Browser:** a real headless Chromium through Playwright. Navigate, click, type, screenshot, and pull console and network errors to reproduce a bug.

Writes, shell commands, and browser clicks ask before they run. Reads run on their own.

## Install

You need Python 3.13.

```bash
git clone git@github.com:shameemreza/heya.git
cd heya
python3.13 -m venv .venv
.venv/bin/pip install -e .
```

The browser tools are optional, since they pull in Playwright and a Chromium binary. Add them when you want them:

```bash
.venv/bin/pip install -e ".[browser]"
.venv/bin/python -m playwright install chromium
```

Heya runs fine without them. The browser tools just return an install hint until you do.

## Run it

The built-in default points at a local model through Ollama on the standard port. With a model running:

```bash
heya "read the files in this folder and tell me what this project does"
```

Or open an interactive session and keep the conversation going:

```bash
heya
```

A task on the command line runs once and exits. Bare `heya` stays open until you type `exit` or `quit`.

Useful flags: `--profile` to pick a model, `--auto-approve` to skip the write/command prompts, `--allow DIR` to add an allowed folder, `--no-self-review` to skip the review pass.

## Configure

Heya reads `~/.config/heya/config.toml`. Everything has a default, so the file is optional.

```toml
[profiles.my-cloud]
base_url = "https://openrouter.ai/api/v1"
model = "some/model-id"
provider_type = "api_key"
api_key_env = "OPENROUTER_API_KEY"

[search]
provider = "brave"
api_key_env = "BRAVE_API_KEY"

[guidance]
paths = ["~/path/to/your/skills"]

[workspace]
allowed_roots = ["~/projects"]

[browser]
headless = false
```

API keys never live in the config file or the repo. You name the environment variable that holds the key, and Heya reads it at runtime. Pick a profile with `--profile` or the `HEYA_PROFILE` environment variable.

## Status

Heya is in active development. The core loop and every tool group above work and are covered by tests. Still to come: a first-run setup that detects local models, OS keychain support for keys, and direct adapters for the Anthropic and Codex APIs.
