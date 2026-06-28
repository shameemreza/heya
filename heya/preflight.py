"""Fast, best-effort check that the active model is actually usable.

Never raises: any error resolves to a status string so startup can show a
friendly hint instead of a traceback."""
from __future__ import annotations

from pathlib import Path

import httpx

from .config import Profile, resolve_api_key

OK = "ok"
UNREACHABLE = "unreachable"
MODEL_MISSING = "model_missing"
NO_KEY = "no_key"


def check_profile(profile: Profile, *, client: httpx.Client | None = None,
                  timeout: float = 1.5, credentials_path: Path | None = None) -> str:
    if profile.provider_type in ("api_key", "oauth"):
        key = resolve_api_key(profile, credentials_path=credentials_path)
        return OK if key else NO_KEY
    # local: probe the OpenAI-compatible /models endpoint
    own = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        resp = client.get(f"{profile.base_url}/models")
        resp.raise_for_status()
        ids = {m.get("id") for m in (resp.json().get("data") or [])}
        return OK if profile.model in ids else MODEL_MISSING
    except Exception:
        return UNREACHABLE
    finally:
        if own:
            client.close()
