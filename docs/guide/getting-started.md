# Getting started

This walks you from a clone to your first useful run.

## Install

You need Python 3.11 or newer. The package is `heya-agent`; the command is
`heya`.

```bash
pipx install heya-agent
```

[pipx](https://pipx.pypa.io) puts `heya` on your PATH in its own isolated
environment. Plain `pip install heya-agent` also works. The browser tools are
optional and pull in Playwright plus a Chromium binary:

```bash
pipx install "heya-agent[browser]"
python -m playwright install chromium
```

## Point it at a model

The fastest way is the setup wizard:

```bash
heya init
```

It walks you through a local or cloud model and writes the config for you. A
pasted cloud key goes into a locked credentials file, never into the config.

If you would rather configure by hand, Heya talks to any OpenAI-compatible chat
endpoint. Copy the example config:

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

The wizard stores your key for you. To configure by hand instead, add a profile
and either let the wizard save the key or set the env var that holds it. Heya
resolves a key from the named env var first, then from the locked credentials
file.

```toml
[profiles.cloud]
base_url = "https://openrouter.ai/api/v1"
model = "anthropic/claude-sonnet-4-6"
provider_type = "api_key"
api_key_env = "OPENROUTER_API_KEY"
```

```bash
export OPENROUTER_API_KEY=sk-...
heya --profile cloud "hello"
```

You can also pick a profile with the `HEYA_PROFILE` env var.

## First runs

Run a one-shot task:

```bash
heya "list the python files in this repo and what each does"
```

Start an interactive session by omitting the task:

```bash
heya
```

Add a working folder so the file and command tools can reach it:

```bash
heya --allow ~/sites/my-store "read the latest WordPress debug log and tell me the last fatal"
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
- [Connect your own MCP servers](mcp.md) to add tools.
