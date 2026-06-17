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
    if not isinstance(raw, list):
        raise ConfigError(
            f"workspace.allowed_roots must be a list of paths, got {type(raw).__name__}"
        )
    for entry in raw:
        if not isinstance(entry, str):
            raise ConfigError(
                f"workspace.allowed_roots entries must be strings, got {entry!r}"
            )
    return tuple(Path(p).expanduser().resolve() for p in raw)


def load_guidance_paths(config_path: Path | None = None) -> tuple[Path, ...]:
    """User guidance folders the read_guidance tool searches, on top of the
    bundled baseline.

    User file shape:
        [guidance]
        paths = ["~/dotbrain/shared/skills", "/abs/team/guidance"]

    Defaults to no user folders (empty) when unset; the bundled baseline is
    added by the CLI, not here.
    """
    path = config_path or default_config_path()
    if not path.exists():
        return ()
    data = tomllib.loads(path.read_text())
    raw = data.get("guidance", {}).get("paths")
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise ConfigError(
            f"guidance.paths must be a list of paths, got {type(raw).__name__}"
        )
    for entry in raw:
        if not isinstance(entry, str):
            raise ConfigError(f"guidance.paths entries must be strings, got {entry!r}")
    return tuple(Path(p).expanduser().resolve() for p in raw)


KNOWN_SEARCH_PROVIDERS = frozenset({"duckduckgo", "brave", "tavily"})


@dataclass(frozen=True)
class SearchConfig:
    provider: str = "duckduckgo"
    api_key_env: str | None = None  # env var NAME holding the key, never the key

    @property
    def api_key(self) -> str | None:
        if self.api_key_env is None:
            return None
        return os.environ.get(self.api_key_env)


def load_search_config(config_path: Path | None = None) -> SearchConfig:
    """Web-search provider selection.

    User file shape:
        [search]
        provider = "brave"            # duckduckgo (default, keyless) | brave | tavily
        api_key_env = "BRAVE_API_KEY" # required for brave/tavily; never the key itself
    """
    path = config_path or default_config_path()
    if not path.exists():
        return SearchConfig()
    data = tomllib.loads(path.read_text())
    raw = data.get("search")
    if not raw:
        return SearchConfig()
    provider = raw.get("provider", "duckduckgo")
    if provider not in KNOWN_SEARCH_PROVIDERS:
        known = ", ".join(sorted(KNOWN_SEARCH_PROVIDERS))
        raise ConfigError(f"Unknown search provider {provider!r}. Known: {known}")
    return SearchConfig(provider=provider, api_key_env=raw.get("api_key_env"))


def load_browser_headless(config_path: Path | None = None) -> bool:
    """Whether the browser runs headless (default) or visibly.

    User file shape:
        [browser]
        headless = false   # watch the browser work; default true
    """
    path = config_path or default_config_path()
    if not path.exists():
        return True
    data = tomllib.loads(path.read_text())
    return bool(data.get("browser", {}).get("headless", True))


def load_wp_path(config_path: Path | None = None) -> Path | None:
    """Default WordPress root for the WP tools, if the user sets one.

    User file shape:
        [wordpress]
        path = "~/Herd/my-site"   # optional; tools also accept a per-call path

    Returns None when unset — the tools then use a per-call path or the cwd.
    """
    path = config_path or default_config_path()
    if not path.exists():
        return None
    data = tomllib.loads(path.read_text())
    raw = data.get("wordpress", {}).get("path")
    if not raw:
        return None
    if not isinstance(raw, str):
        raise ConfigError(f"wordpress.path must be a string, got {type(raw).__name__}")
    return Path(raw).expanduser().resolve()


def load_approval_allow(config_path: Path | None = None) -> tuple[str, ...]:
    """Command prefixes that auto-approve, skipping the gate (fail-closed).

    User file shape:
        [approval]
        allow = ["wp plugin list", "wp option get", "git status"]

    A gated command auto-approves only when it starts with one of these. No
    denylist — anything not listed still prompts. Defaults to none.
    """
    path = config_path or default_config_path()
    if not path.exists():
        return ()
    data = tomllib.loads(path.read_text())
    raw = data.get("approval", {}).get("allow")
    if not raw:
        return ()
    if not isinstance(raw, list) or not all(isinstance(e, str) for e in raw):
        raise ConfigError("approval.allow must be a list of strings.")
    return tuple(raw)


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
