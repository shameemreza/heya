"""Interactive first-run setup: pick cloud or local, get a working model.

Numbered menus, reads from an injectable stream, writes via an injectable sink,
so it is fully testable offline. Never installs Ollama; only pulls a model with
explicit consent. A pasted key goes to the locked credentials store."""
from __future__ import annotations

import getpass
import subprocess
import sys
from pathlib import Path

from .config import Profile, default_config_path, upsert_profile
from .credentials import save_key
from .llm_client import LLMClient

# (label, profile_name, base_url, model, api_key_env)
_PROVIDERS = [
    ("OpenRouter (one key, many models)", "cloud", "https://openrouter.ai/api/v1",
     "openrouter/auto", "OPENROUTER_API_KEY"),
    ("OpenAI", "cloud", "https://api.openai.com/v1", "gpt-4o-mini", "OPENAI_API_KEY"),
    ("Anthropic", "cloud", "https://api.anthropic.com/v1", "claude-haiku-4-5", "ANTHROPIC_API_KEY"),
]
_DEFAULT_LOCAL_MODEL = "qwen2.5-coder:14b"
_LOCAL_BASE_URL = "http://localhost:11434/v1"


def _default_verify(profile: Profile, key: str) -> bool:
    try:
        LLMClient(profile, api_key=key).chat([{"role": "user", "content": "ping"}])
        return True
    except Exception:
        return False


def _read_secret(stream, out, prompt: str) -> str:
    """Read a secret value without echoing it when on a real interactive TTY."""
    out(prompt)
    if stream is sys.stdin and sys.stdin.isatty():
        return getpass.getpass("").strip()
    line = stream.readline()
    if line == "":
        raise EOFError
    return line.strip()


def run_init(*, stream=None, write=None, config_path: Path | None = None,
             credentials_path: Path | None = None, verify=None, runner=None) -> int:
    stream = stream or sys.stdin
    out = write or (lambda s: (sys.stdout.write(s), sys.stdout.flush()) and None)
    config_path = config_path or default_config_path()
    verify = verify or _default_verify
    runner = runner or (lambda cmd: subprocess.run(cmd).returncode)

    def ask(prompt: str) -> str:
        out(prompt)
        line = stream.readline()
        if line == "":
            raise EOFError
        return line.strip()

    out("\n  Welcome to Heya. Let's pick how you want to run the AI.\n\n")

    if config_path.exists():
        if ask("  A config already exists. Update it? [y/N]: ").lower() != "y":
            out("  No changes made.\n")
            return 1

    choice = ask("  1) Cloud  - easiest, paste one key\n"
                 "  2) Local  - free & private, one-time download\n"
                 "  Choose [1]: ") or "1"

    if choice == "2":
        return _setup_local(ask, out, config_path, runner)
    return _setup_cloud(stream, ask, out, config_path, credentials_path, verify)


def _setup_cloud(stream, ask, out, config_path, credentials_path, verify) -> int:
    out("\n  Which provider?\n")
    for i, (label, *_rest) in enumerate(_PROVIDERS, 1):
        out(f"  {i}) {label}\n")
    raw = ask("  Choose [1]: ") or "1"
    try:
        label, name, base_url, model, env = _PROVIDERS[int(raw) - 1]
    except (ValueError, IndexError):
        out("  Not a valid choice.\n")
        return 1

    profile = Profile(name=name, base_url=base_url, model=model,
                      provider_type="api_key", api_key_env=env)
    while True:
        key = _read_secret(stream, out, "  Paste your API key: ")
        if not key:
            out("  No key entered.\n")
            return 1
        out("  Checking the key...\n")
        if verify(profile, key):
            break
        out("  That key did not work. Try a different key, or press Enter to abort.\n")

    save_key(name, key, path=credentials_path)
    upsert_profile(config_path, name, {
        "base_url": base_url, "model": model,
        "provider_type": "api_key", "api_key_env": env,
    })
    out(f"\n  You're ready. Using {label} ({model}).\n\n")
    return 0


def _setup_local(ask, out, config_path, runner) -> int:
    model = ask(f"  Model name [{_DEFAULT_LOCAL_MODEL}]: ") or _DEFAULT_LOCAL_MODEL
    if ask(f"  Download {model} now with `ollama pull`? [Y/n]: ").lower() != "n":
        out(f"  Pulling {model} (this can take a few minutes)...\n")
        code = runner(["ollama", "pull", model])
        if code != 0:
            out("  The download did not finish. You can re-run `heya init` later.\n")
            return 1
    upsert_profile(config_path, "local", {
        "base_url": _LOCAL_BASE_URL, "model": model, "provider_type": "local",
    })
    out(f"\n  You're ready. Using local model {model}.\n\n")
    return 0
