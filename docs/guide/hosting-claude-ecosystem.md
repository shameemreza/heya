# Hosting your Claude skills, plugins, and tools

Heya reads the same directories Claude Code uses, so the skills, plugins, hooks,
commands, and sub-agents you already have work in Heya with no re-install. Heya
loads them as text and config. Nothing runs code just by being present.

## Skills

Heya discovers `SKILL.md`-format skills from `~/.claude/skills`, your project's
`.claude/skills`, and any enabled plugin. Each skill's name and description go
into the system prompt, and Heya loads the full skill on demand with a `Skill`
tool when it matches the task.

```bash
heya "use my writing-support skill to draft a reply to this ticket: ..."
```

Tool names are translated, so a skill that asks for `Read`, `Edit`, or `Bash`
maps to Heya's `read_file`, `write_file`, and `run_command`.

Turn discovery off or change the paths in `[skills]`.

## Plugins

Heya discovers installed plugins under `~/.claude/plugins/cache` and loads their
skills, namespaced as `plugin:skill` (for example `superpowers:brainstorming`).
Disable specific plugins or change the roots in `[plugins]`.

## Commands

Flat `commands/*.md` files (your slash commands) load as invokable skills, from
`~/.claude/commands`, your project, and plugins. Configure them in `[commands]`.

## Sub-agents

Claude agent definitions (`agents/*.md`) become Heya roles. Their tools and
system prompt carry over, and you can delegate to one:

```bash
heya "spawn the security-reviewer agent to check this diff"
```

A discovered agent only sets a child's system prompt and tool allow-list. It
cannot grant tools Heya does not have, and it cannot bypass the approval gate.
Configure the paths in `[agents]`.

## Hooks

Heya can run Claude-style command hooks at lifecycle points: session start,
before a tool runs (which can block it), after a tool runs, on a user prompt, and
on stop. Because hooks run shell, they are off by default. Turn them on only when
you trust the hook configs:

```toml
[hooks]
enabled = true
# sources = ["~/.claude/settings.json"]
```

A hook receives the event as JSON on standard input. A PreToolUse hook that exits
with code 2 blocks the tool. A misbehaving hook is a non-blocking event; it never
crashes the loop.

## What is not hosted yet

MCP servers defined inside a plugin, language servers, themes, and the
marketplace install flow are not loaded yet. Heya's own MCP support connects
servers you configure directly.
