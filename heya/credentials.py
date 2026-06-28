"""Locked, gitignored store for pasted API keys.

Keys live here, never in config.toml, code, or logs. File mode is 0o600."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

from .tomlw import dumps


def default_credentials_path() -> Path:
    return Path.home() / ".config" / "heya" / "credentials.toml"


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text())


def save_key(profile_name: str, key: str, *, path: Path | None = None) -> None:
    path = path or default_credentials_path()
    data = _read(path)
    entry = data.get(profile_name, {})
    entry["api_key"] = key
    data[profile_name] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create at 0o600 so the key is never briefly world-readable between the
    # write and a chmod. chmod after too, to tighten a pre-existing looser file.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(dumps(data))
    os.chmod(path, 0o600)


def load_key(profile_name: str, *, path: Path | None = None) -> str | None:
    path = path or default_credentials_path()
    return _read(path).get(profile_name, {}).get("api_key")
