"""Configuration: providers, profiles, and active-profile resolution.

The model is configuration, not architecture. A Profile fully describes how to
reach a model (endpoint, model id, auth, type). Profiles are switchable; nothing
in the agent assumes a specific model or runner.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

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
