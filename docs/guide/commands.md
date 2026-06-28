# Commands and usage

Heya runs in two modes and takes a few flags. Inside an interactive session,
slash commands control the model, your saved sessions, and what is loaded.

## Run it

```bash
heya                          # an interactive session
heya "fix the failing test"   # run one task and exit
heya init                     # set up a model, local or cloud
```

Attach a file or an image by writing `@` and the path. With a vision model, Heya
reads a screenshot directly:

```bash
heya "what is failing here? @debug.log @error.png"
```

## Flags

- `--continue` resume the most recent session.
- `--resume [id]` resume a session by id, or the latest if you leave the id off.
- `--profile <name>` use a specific model profile from your config.
- `--allow <dir>` add a folder Heya may read and write in. Repeatable.
- `--auto-approve` run write and command tools without asking first. Use with care.
- `--no-self-review` skip the scoped self-review pass.
- `--max-iters <n>` cap the tool loop per task.
- `--version` print the version.

## Slash commands

Type these inside an interactive session.

- `/help` list the commands.
- `/model` show the active profile. `/model <name>` switches to another.
- `/sessions` list your saved sessions.
- `/resume <id>` load a saved session into the current one.
- `/save [title]` save now, with an optional title.
- `/new` start a fresh session.
- `/clear` reset the conversation but keep the current session.
- `/compact` compact the conversation context now.
- `/cost` show the token usage so far.
- `/skills` list the skills Heya loaded.
- `/agents` list the sub-agent roles.
- `/mcp` list the tools from connected MCP servers.
- `/quit` exit. Ctrl-D works too.
