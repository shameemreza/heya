# Background agents

Heya can run sub-agents in the background while you and the main agent keep
working. Use them to offload long or parallel work: audit a plugin, research a
problem, or build a whole plugin or theme, all without blocking your session.

## How it works

Ask for background work in plain language, or let the main agent offload a
subtask on its own. Each background agent gets an id like `a1`. You keep
working; when it finishes, Heya prints a notice and you can collect its result.

## Reading and writing

A background agent that only reads (an audit, research, a review) needs nothing
special and several can run at once. A background agent that builds or changes
files declares the folder it owns. That folder is leased to it, so nothing else
writes there until it finishes, and two agents building two different plugins
never collide. You authorize a writing or command-running agent once, when it
starts; after that it runs on its own within that grant.

## Controlling them

- See what is running with a status list.
- Read progress from one agent at any time.
- Get the final result when it is done.
- Cancel one; it stops at its next safe checkpoint.

Background agents run inside your Heya session. Quitting Heya ends them, and
their finished results are saved with the session so a resume shows what ran.

## A limit you can set

Set how many run at once in `config.toml`:

    [agents]
    max_background = 4
