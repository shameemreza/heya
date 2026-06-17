"""Read-only guidance grounding.

Guidance is folders of markdown. Each source yields one item per SKILL.md-bearing
subfolder and per loose .md file. Sources are searched in order (bundled first,
then user folders), so a user item overrides a bundled item of the same name.
read_guidance lists items or returns one item's text — it never writes, and it is
not allow-list- or approval-gated, because its sources are intentionally shared.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

BUNDLED_GUIDANCE_DIR = Path(__file__).resolve().parent / "guidance"


@dataclass(frozen=True)
class GuidanceItem:
    name: str
    description: str
    path: Path

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}
    fm: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" in line:
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip()
    return fm


def _describe(text: str, fallback: str) -> str:
    fm = _frontmatter(text)
    if fm.get("description"):
        return fm["description"]
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("---") or stripped.startswith("#"):
            continue
        return stripped[:200]
    return fallback


def collect_guidance(sources: Sequence[Path]) -> dict[str, GuidanceItem]:
    """Map guidance name -> item across sources; later sources win on collision."""
    items: dict[str, GuidanceItem] = {}
    for source in sources:
        source = Path(source)
        if not source.is_dir():
            continue
        for entry in sorted(source.iterdir()):
            if entry.is_dir():
                skill = entry / "SKILL.md"
                if skill.is_file():
                    items[entry.name] = GuidanceItem(
                        entry.name, _describe(skill.read_text(encoding="utf-8"), entry.name), skill
                    )
            elif entry.suffix.lower() == ".md":
                items[entry.stem] = GuidanceItem(
                    entry.stem, _describe(entry.read_text(encoding="utf-8"), entry.stem), entry
                )
    return items


def read_guidance(name: str | None = None, *, sources: Sequence[Path]) -> str:
    """List available guidance, or return one item's text by name."""
    items = collect_guidance(sources)
    if not items:
        return "No guidance is available."
    if not name:
        lines = ["Available guidance (call read_guidance with a name to read one):"]
        lines += [f"- {n}: {items[n].description}" for n in sorted(items)]
        return "\n".join(lines)
    item = items.get(name)
    if item is None:
        return f"No guidance named {name!r}. Available: {', '.join(sorted(items))}"
    return item.read()
