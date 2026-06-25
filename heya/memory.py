"""File-backed long-term memory: one typed markdown fact per file, plus an index.

The model recalls from a one-line index loaded into context and reads full facts on
demand; it saves/updates/forgets autonomously. Writes are confined to the memory
folder. No embeddings — the index-in-context + read-on-demand model.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

MEMORY_TYPES = ("user", "feedback", "project", "reference")

_INDEX_FILE = "MEMORY.md"
_INDEX_HEADER = "# Memory index\n"


def _slug(name: str) -> str:
    """A safe kebab filename stem confined to a single path segment."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (flat frontmatter dict, body). Body is everything after the 2nd ---."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text
    fm: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" in line:
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip()
    body = "\n".join(lines[end + 1:]).lstrip("\n")
    return fm, body


def serialize_memory(name: str, description: str, type: str, content: str) -> str:
    return f"---\nname: {name}\ndescription: {description}\ntype: {type}\n---\n{content.rstrip()}\n"


@dataclass(frozen=True)
class MemoryItem:
    name: str
    description: str
    type: str
    path: Path

    def read(self) -> str:
        _, body = parse_frontmatter(self.path.read_text(encoding="utf-8", errors="replace"))
        return body


class MemoryStore:
    def __init__(self, root, *, notify: Callable[[str], None] | None = None) -> None:
        self.root = Path(root)
        self._notify = notify

    def _path_for(self, name: str) -> Path:
        slug = _slug(name)
        if not slug:
            raise ValueError("memory name must contain letters or digits")
        path = (self.root / f"{slug}.md").resolve()
        if path.parent != self.root.resolve():
            raise ValueError("memory name must be a single path segment")
        return path

    def _items(self) -> list[MemoryItem]:
        items: list[MemoryItem] = []
        if not self.root.is_dir():
            return items
        for entry in sorted(self.root.iterdir()):
            if entry.suffix.lower() != ".md" or entry.name == _INDEX_FILE:
                continue
            fm, _ = parse_frontmatter(entry.read_text(encoding="utf-8", errors="replace"))
            items.append(MemoryItem(
                name=fm.get("name", entry.stem),
                description=fm.get("description", ""),
                type=fm.get("type", ""),
                path=entry,
            ))
        return items

    def index_count(self) -> int:
        return len(self._items())

    def load_index(self) -> str:
        items = self._items()
        if not items:
            return ""
        lines = [_INDEX_HEADER.rstrip("\n")]
        lines += [f"- {it.name} ({it.type}): {it.description}" for it in items]
        return "\n".join(lines) + "\n"

    def _rebuild_index(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / _INDEX_FILE).write_text(self.load_index() or _INDEX_HEADER, encoding="utf-8")

    def read(self, name: str) -> str:
        try:
            path = self._path_for(name)
        except ValueError as exc:
            return f"Error: {exc}"
        if not path.is_file():
            return f"No memory named {_slug(name)!r}."
        _, body = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        return body

    def save(self, name: str, description: str, type: str, content: str) -> str:
        if type not in MEMORY_TYPES:
            return f"Error: memory type must be one of {', '.join(MEMORY_TYPES)}."
        try:
            path = self._path_for(name)
        except ValueError as exc:
            return f"Error: {exc}"
        self.root.mkdir(parents=True, exist_ok=True)
        existed = path.is_file()
        path.write_text(serialize_memory(path.stem, description, type, content), encoding="utf-8")
        self._rebuild_index()
        verb = "updated" if existed else "remembered"
        if self._notify:
            self._notify(f"{verb}: {path.stem} — {description}")
        return f"Memory {path.stem!r} {verb}."
