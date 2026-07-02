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
endpoint. Create `~/.config/heya/config.toml` with a `[profiles.<name>]` block
(the repo's `config.example.toml` is a full template, but it is not bundled in the
installed package):

```toml
[profiles.cloud]
base_url = "https://openrouter.ai/api/v1"
model = "anthropic/claude-sonnet-4-6"
provider_type = "api_key"
api_key_env = "OPENROUTER_API_KEY"
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

### Which models work

Heya talks to any endpoint that speaks the OpenAI chat API, so you are not tied
to one provider:

- Local, free and private: Ollama, LM Studio, or any local OpenAI-compatible server.
- OpenRouter: one key reaches Claude, GPT, Gemini, Kimi, GLM, DeepSeek, Llama, and more. Set `model` to any id OpenRouter lists.
- OpenAI directly: `base_url = "https://api.openai.com/v1"` and your model.
- Anything else with an OpenAI-compatible API: point `base_url` at it.

A bigger cloud model handles the hard problems; a local one is free and keeps
your code on your machine. Switch between them in a session with `/model`.

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

## Keeping it current

Run `heya update` to upgrade to the latest release. Heya also tells you at
startup when a newer version is available.

## Where to go next

- [Configuration reference](configuration.md) for every config block.
- [The diagnostic workflow](diagnostic-workflow.md) to triage a bug or a backlog.
- [Hosting your Claude skills, plugins, and tools](hosting-claude-ecosystem.md).
- [Tools and safety](tools-and-safety.md) for what runs without asking.
- [Connect your own MCP servers](mcp.md) to add tools.
