# Getting started

This walks you from a clone to your first useful run.

## Install

You need Python 3.13.

```bash
git clone git@github.com:shameemreza/heya.git
cd heya
python3.13 -m venv .venv
.venv/bin/pip install -e .
```

That gives you a `heya` command inside the virtualenv. The browser tools are
optional and pull in Playwright plus a Chromium binary:

```bash
.venv/bin/pip install -e ".[browser]"
.venv/bin/python -m playwright install chromium
```

## Point it at a model

Heya talks to any OpenAI-compatible chat endpoint. Copy the example config:

```bash
mkdir -p ~/.config/heya
cp config.example.toml ~/.config/heya/config.toml
```

### A local model

Install Ollama, pull a model, and you are done. The default profile already
points at Ollama's endpoint.

```bash
ollama pull qwen2.5-coder:14b
```

If you use a different model, set the name in your config under
`[profiles.local]`.

### A cloud model

Add a profile and set the env var that holds your key. Heya reads keys from the
named env var, it never stores them.

```toml
[profiles.cloud]
base_url = "https://openrouter.ai/api/v1"
model = "anthropic/claude-sonnet-4-6"
provider_type = "api_key"
api_key_env = "OPENROUTER_API_KEY"
```

```bash
export OPENROUTER_API_KEY=sk-...
.venv/bin/heya --profile cloud "hello"
```

You can also pick a profile with the `HEYA_PROFILE` env var.

## First runs

Run a one-shot task:

```bash
.venv/bin/heya "list the python files in this repo and what each does"
```

Start an interactive session by omitting the task:

```bash
.venv/bin/heya
```

Add a working folder so the file and command tools can reach it:

```bash
.venv/bin/heya --allow ~/sites/my-store "read the latest WordPress debug log and tell me the last fatal"
```

## Common flags

- `--profile NAME` pick a model profile.
- `--allow DIR` add an allowed folder (repeatable).
- `--auto-approve` run write and command tools without prompting. Use with care.
- `--no-self-review` skip the scoped self-review pass.
- `--max-iters N` cap the tool loop per task.

## Where to go next

- [Configuration reference](configuration.md) for every config block.
- [The diagnostic workflow](diagnostic-workflow.md) to triage a bug or a backlog.
- [Hosting your Claude skills, plugins, and tools](hosting-claude-ecosystem.md).
- [Tools and safety](tools-and-safety.md) for what runs without asking.
