"""Self-update: a throttled PyPI check, a startup notice, and an install-aware
`heya update` command. Best-effort throughout: every function fails silent and
never raises."""
from __future__ import annotations


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
