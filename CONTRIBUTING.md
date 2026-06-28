# Contributing to Heya

Thanks for your interest. Heya is a single, local-first, tool-using agent in
plain Python, no framework, so every part is easy to read and change.

## Set up

```bash
git clone git@github.com:shameemreza/heya.git
cd heya
python3.13 -m venv .venv
.venv/bin/pip install -e ".[browser]"
.venv/bin/python -m playwright install chromium   # only if you want the browser tools
```

## Run the tests

```bash
.venv/bin/pytest             # the fast suite
.venv/bin/pytest -m integration   # the live ones (need a model endpoint or external CLI)
```

Keep the suite green. New behavior comes with a test.

## Style

- Small, focused files and functions. Match the surrounding code.
- Comments only for non-obvious intent or a constraint, not to narrate the code.
- Tools never raise into the agent loop; they return an `Error: ...` string.
- File and command tools stay confined to the allow-list.

## Writing

For any prose (README, docs, commit bodies), follow Heya's own voice:
`heya/guidance/writing-voice.md` and `heya/guidance/banned-words.md`. Plain,
direct, first person where natural. No em dashes for pauses, no emoji unless the
context already uses them, and no AI attribution anywhere. Conventional commits
in lowercase, for example `feat: add the thing` or `fix: handle the edge case`.
