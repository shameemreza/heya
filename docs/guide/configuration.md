# Configuration reference

Heya reads `~/.config/heya/config.toml`. Every block is optional; Heya runs with
sensible defaults if the file is missing. The shipped `config.example.toml` has a
copy-paste template of all of this.

## Models: `[profiles.<name>]`

A profile fully describes how to reach one model.

```toml
[profiles.local]
base_url = "http://localhost:11434/v1"
model = "qwen2.5-coder:14b"
provider_type = "local"        # local | api_key | oauth
context_window = 32768         # used for context compaction
# api_key_env = "SOME_KEY"     # the NAME of the env var holding the key
# timeout = 600                # request timeout in seconds
```

Pick the active profile with `heya --profile <name>` or the `HEYA_PROFILE` env
var. The default profile is `local`.

## Cheaper secondary model: `[routing]`

Route compaction summaries and explicitly-marked sub-agent tasks to a cheaper
profile. It names another profile. Unset means off.

```toml
[routing]
weak_profile = "local-small"
```

## Context management: `[context]`

```toml
[context]
threshold = 0.85            # compact at this fraction of the window
reserve_tokens = 2048       # headroom for the reply
keep_recent_tokens = 4096   # verbatim recent-tail budget
task_token_budget = 200000  # per-task ceiling; 0 = unlimited
```

## Working folders: `[workspace]`

The file and command tools are confined to these folders. The current directory
is always allowed.

```toml
[workspace]
allowed_roots = ["~/projects", "/abs/path/site"]
```

## Identity: `[identity]`

The persona Heya writes as. Leave it unset for the generic default voice. The
writing style is bundled either way.

```toml
[identity]
name = "Your Name"
role = "WooCommerce Happiness Engineer"
```

## Web search: `[search]`

```toml
[search]
provider = "duckduckgo"     # duckduckgo (keyless) | brave | tavily
# api_key_env = "BRAVE_API_KEY"
```

## Hosting your Claude ecosystem

Heya reads your existing Claude directories by default. Turn any of them off or
point them elsewhere. See [hosting-claude-ecosystem.md](hosting-claude-ecosystem.md).

```toml
[skills]
enabled = true
# paths = ["~/.claude/skills"]

[plugins]
enabled = true
# paths = ["~/.claude/plugins/cache"]
# disabled = ["plugin-name"]

[commands]
enabled = true

[agents]
enabled = true

[hooks]
enabled = false             # hooks run shell, so they are off by default
# sources = ["~/.claude/settings.json"]
```

## Browser: `[browser]`

```toml
[browser]
headless = true             # set false to watch a reproduction run
```

## WordPress: `[wordpress]`

A default local WordPress path for the wp-cli and log tools.

```toml
[wordpress]
path = "~/sites/my-store"
```

## Memory: `[memory]`

Where Heya keeps its remembered facts.

```toml
[memory]
path = "~/.config/heya/memory"
```
