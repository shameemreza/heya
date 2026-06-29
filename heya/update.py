"""Self-update: a throttled PyPI check, a startup notice, and an install-aware
`heya update` command. Best-effort throughout: every function fails silent and
never raises."""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

from .config import default_config_path


def _parts(v) -> tuple[int, ...]:
    """The leading-digit numeric parts of a version, e.g. '0.2.0rc1' -> (0, 2, 0)."""
    out: list[int] = []
    for token in str(v).split("."):
        digits = ""
        for ch in token:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    return tuple(out)


def is_newer(latest, current) -> bool:
    """True if `latest` is a newer version than `current`. False on any error."""
    try:
        lp, cp = _parts(latest), _parts(current)
        n = max(len(lp), len(cp))
        lp = lp + (0,) * (n - len(lp))
        cp = cp + (0,) * (n - len(cp))
        return lp > cp
    except Exception:
        return False


def cache_path() -> Path:
    return default_config_path().parent / "update-cache.json"


def read_cache(path=None) -> dict:
    p = Path(path) if path is not None else cache_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_cache(data, path=None) -> None:
    p = Path(path) if path is not None else cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


PYPI_URL = "https://pypi.org/pypi/heya-agent/json"
TTL = 86400  # seconds; check at most about once a day


def fetch_latest(timeout: float = 2.0):
    """The latest heya-agent version on PyPI, or None on any failure."""
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["info"]["version"]
    except Exception:
        return None


def _refresh(clock, fetcher, cache_file) -> None:
    """Fetch the latest version and rewrite the cache. Best-effort."""
    try:
        write_cache({"checked": clock(), "latest": fetcher()}, cache_file)
    except Exception:
        pass


def update_notice(current, *, enabled=True, clock=time.time, fetcher=fetch_latest,
                  cache_file=None, spawn=True):
    """Return a newer version to tell the user about, or None.

    Never blocks: the answer comes from the cache, and a stale cache triggers a
    daemon-thread refresh for next time. Does nothing when disabled."""
    if not enabled:
        return None
    cache = read_cache(cache_file)
    try:
        stale = (clock() - float(cache.get("checked", 0))) > TTL
    except Exception:
        stale = True
    if stale and spawn:
        try:
            threading.Thread(target=_refresh, args=(clock, fetcher, cache_file),
                             daemon=True).start()
        except Exception:
            pass
    latest = cache.get("latest")
    if latest and is_newer(latest, current):
        return latest
    return None
