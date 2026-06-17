"""Configuration: providers, profiles, and active-profile resolution.

The model is configuration, not architecture. A Profile fully describes how to
reach a model (endpoint, model id, auth, type). Profiles are switchable; nothing
in the agent assumes a specific model or runner.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT = 120.0
DEFAULT_PROFILE = "local"


class ConfigError(Exception):
    """Raised when configuration cannot be resolved."""


@dataclass(frozen=True)
class Profile:
    name: str
    base_url: str
    model: str
    provider_type: str = "local"  # "local" | "api_key" | "oauth"
    api_key_env: str | None = None  # env var NAME holding the key, never the key itself
    timeout: float = DEFAULT_TIMEOUT

    @property
    def api_key(self) -> str | None:
        if self.api_key_env is None:
            return None
        return os.environ.get(self.api_key_env)


def resolve_profile(
    name: str | None = None,
    *,
    profiles: dict[str, Profile],
) -> Profile:
    """Resolve the active profile.

    Precedence: explicit name > HEYA_PROFILE env var > DEFAULT_PROFILE.
    """
    chosen = name or os.environ.get("HEYA_PROFILE") or DEFAULT_PROFILE
    if chosen not in profiles:
        available = ", ".join(sorted(profiles))
        raise ConfigError(f"Unknown profile {chosen!r}. Available: {available}")
    return profiles[chosen]


# Built-in presets. `local` is the reference default; users add or override
# their own in ~/.config/heya/config.toml. The cloud example shows that
# switching providers is config, not code.
BUILTIN_PROFILES: dict[str, Profile] = {
    "local": Profile(
        name="local",
        base_url="http://localhost:11434/v1",
        model="gemma4:12b",
        provider_type="local",
    ),
    "cloud-openrouter": Profile(
        name="cloud-openrouter",
        base_url="https://openrouter.ai/api/v1",
        model="openrouter/auto",  # user picks any model id OpenRouter exposes
        provider_type="api_key",
        api_key_env="OPENROUTER_API_KEY",
    ),
}


def default_config_path() -> Path:
    return Path.home() / ".config" / "heya" / "config.toml"


def default_allowed_roots() -> tuple[Path, ...]:
    """The working directory is the sole allowed root unless config widens it."""
    return (Path.cwd().resolve(),)


def load_allowed_roots(config_path: Path | None = None) -> tuple[Path, ...]:
    """Folders the file/command tools may operate within.

    User file shape:
        [workspace]
        allowed_roots = ["~/projects/foo", "/abs/path/bar"]

    Defaults to the current working directory when no config is present.
    """
    path = config_path or default_config_path()
    if not path.exists():
        return default_allowed_roots()
    data = tomllib.loads(path.read_text())
    raw = data.get("workspace", {}).get("allowed_roots")
    if not raw:
        return default_allowed_roots()
    return tuple(Path(p).expanduser().resolve() for p in raw)


def load_profiles(config_path: Path | None = None) -> dict[str, Profile]:
    """Built-in profiles merged with any user-defined ones from a TOML file.

    User file shape:
        [profiles.<name>]
        base_url = "..."
        model = "..."
        provider_type = "local" | "api_key" | "oauth"
        api_key_env = "SOME_ENV_VAR"   # optional
    """
    profiles = dict(BUILTIN_PROFILES)
    path = config_path or default_config_path()
    if path.exists():
        data = tomllib.loads(path.read_text())
        for name, raw in data.get("profiles", {}).items():
            profiles[name] = Profile(name=name, **raw)
    return profiles
