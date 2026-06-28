"""Persist and restore conversations. A session is one JSON file per id under
the config dir, mode 0o600. Every function is best-effort and never raises."""
from __future__ import annotations

import json
from pathlib import Path


def default_sessions_dir() -> Path:
    return Path.home() / ".config" / "heya" / "sessions"


def _dir(sessions_dir: Path | None) -> Path:
    return sessions_dir or default_sessions_dir()


def derive_title(messages: list[dict]) -> str:
    for m in messages or []:
        if m.get("role") == "user":
            text = m.get("content")
            if isinstance(text, list):  # multimodal: take the first text part
                text = next((p.get("text", "") for p in text if isinstance(p, dict)
                             and p.get("type") == "text"), "")
            text = " ".join(str(text).split())
            if text:
                return text[:60]
    return "untitled"


def save_session(data: dict, *, sessions_dir: Path | None = None) -> Path | None:
    sid = data.get("id")
    if not sid:
        return None
    d = _dir(sessions_dir)
    try:
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{sid}.json"
        path.write_text(json.dumps(data, ensure_ascii=False))
        path.chmod(0o600)
        return path
    except Exception:
        return None


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def load_session(session_id: str, *, sessions_dir: Path | None = None) -> dict | None:
    d = _dir(sessions_dir)
    exact = d / f"{session_id}.json"
    if exact.exists():
        return _read(exact)
    # accept a unique id prefix
    try:
        matches = [p for p in d.glob("*.json") if p.stem.startswith(session_id)]
    except Exception:
        return None
    if len(matches) == 1:
        return _read(matches[0])
    return None


def list_sessions(*, sessions_dir: Path | None = None) -> list[dict]:
    d = _dir(sessions_dir)
    out = []
    try:
        files = list(d.glob("*.json"))
    except Exception:
        return []
    for p in files:
        data = _read(p)
        if not data:
            continue
        out.append({
            "id": data.get("id", p.stem),
            "title": data.get("title", "untitled"),
            "updated": data.get("updated", ""),
            "profile": data.get("profile", ""),
            "messages": len(data.get("messages", [])),
        })
    out.sort(key=lambda s: s.get("updated", ""), reverse=True)
    return out


def latest_session_id(*, sessions_dir: Path | None = None) -> str | None:
    items = list_sessions(sessions_dir=sessions_dir)
    return items[0]["id"] if items else None
