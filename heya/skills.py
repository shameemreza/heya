"""Host Claude SKILL.md skills.

Discovers SKILL.md-format skills from the user's Claude directories, lists them
for the model (a system-prompt skills block), and loads one on demand via the
Skill tool. Mirrors heya/tools_guidance.py. Conservative by design: it loads
instructions as text and applies safe substitutions; it never executes shell a
skill embeds, and does not enforce tool-gating (deferred). Nothing here raises
into the loop (callers wrap)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .tools_guidance import _frontmatter

# Claude tool name -> Heya tool name. Identity for anything unmapped.
CLAUDE_TOOL_ALIASES = {
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "write_file",
    "MultiEdit": "write_file",
    "Bash": "run_command",
    "Grep": "search_files",
    "Glob": "search_files",
    "WebFetch": "web_fetch",
    "WebSearch": "web_search",
}

SKILLS_FRAMING = (
    "Skills available. When a task matches a skill's description, call "
    "Skill(name) to load its full instructions and follow them."
)

_MAX_SKILLS_LISTED = 150


@dataclass(frozen=True)
class SkillItem:
    name: str
    description: str
    when_to_use: str
    directory: Path
    allowed_tools: tuple[str, ...]
    path: Path
    plugin_root: Path | None = None

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8", errors="replace")


def translate_allowed_tools(names) -> tuple[str, ...]:
    out: list[str] = []
    seen = set()
    for n in names:
        mapped = CLAUDE_TOOL_ALIASES.get(n, n)
        if mapped and mapped not in seen:
            seen.add(mapped)
            out.append(mapped)
    return tuple(out)


def _split_tools(raw: str) -> tuple[str, ...]:
    parts = []
    for token in (raw or "").replace(",", " ").split():
        cleaned = token.strip().strip("[]\"'")
        if cleaned and cleaned != "-":
            parts.append(cleaned)
    return tuple(parts)


def parse_skill_frontmatter(text: str) -> dict:
    """Pull the skill fields out of the SKILL.md frontmatter. `allowed_tools` is a
    tuple parsed from a comma- or space-delimited inline value (YAML multi-line
    lists are not parsed in 13a). Missing frontmatter -> empty fields."""
    fm = _frontmatter(text)
    raw_tools = fm.get("allowed-tools", "") or fm.get("allowed_tools", "")
    return {
        "name": fm.get("name", ""),
        "description": fm.get("description", ""),
        "when_to_use": fm.get("when_to_use", "") or fm.get("when-to-use", ""),
        "allowed_tools": _split_tools(raw_tools),
    }


def collect_skills(dirs: Sequence[Path]) -> dict[str, SkillItem]:
    """Map skill name -> SkillItem across dirs; later dirs win on collision (a user
    skill overrides a same-named one earlier in the list). Skips dirs without a
    SKILL.md and never raises."""
    items: dict[str, SkillItem] = {}
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for entry in sorted(d.iterdir()):
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.is_file():
                continue
            try:
                text = skill_md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fm = parse_skill_frontmatter(text)
            name = fm["name"] or entry.name
            description = (fm["description"] or fm["when_to_use"] or name)[:300]
            items[name] = SkillItem(
                name=name, description=description, when_to_use=fm["when_to_use"],
                directory=entry, allowed_tools=translate_allowed_tools(fm["allowed_tools"]),
                path=skill_md,
            )
    return items


def collect_commands(dirs: Sequence[Path]) -> dict[str, SkillItem]:
    """Map command name -> SkillItem from flat `<name>.md` files in each dir
    (Claude slash commands). Later dirs win; missing dirs and unreadable files
    are skipped; never raises. The file's parent is the skill directory."""
    items: dict[str, SkillItem] = {}
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for entry in sorted(d.iterdir()):
            if not entry.is_file() or entry.suffix.lower() != ".md":
                continue
            try:
                text = entry.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fm = parse_skill_frontmatter(text)
            name = fm["name"] or entry.stem
            description = (fm["description"] or fm["when_to_use"] or name)[:300]
            items[name] = SkillItem(
                name=name, description=description, when_to_use=fm["when_to_use"],
                directory=entry.parent, allowed_tools=translate_allowed_tools(fm["allowed_tools"]),
                path=entry,
            )
    return items


def build_skills_block(skills) -> str:
    """The skills section appended to an agent's system prompt. One bounded line
    per skill, and the total count is capped so a large library cannot flood the
    context window; empty -> ''."""
    if not skills:
        return ""
    names = sorted(skills)
    lines = [SKILLS_FRAMING, ""]
    for name in names[:_MAX_SKILLS_LISTED]:
        desc = " ".join((skills[name].description or "").split())[:160]
        lines.append(f"- {name}: {desc}")
    extra = len(names) - _MAX_SKILLS_LISTED
    if extra > 0:
        lines.append(f"- (+{extra} more skills; call Skill(name) if you know the name)")
    return "\n".join(lines)


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    lines = text.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return text
    return "\n".join(lines[end + 1:]).lstrip("\n")


def render_skill(item: SkillItem, arguments: str = "") -> str:
    """Load a skill body with substitutions applied. Does NOT execute embedded
    shell (`` !`cmd` `` is left literal). Safe text only."""
    body = _strip_frontmatter(item.read())
    args = arguments or ""
    body = body.replace("${CLAUDE_SKILL_DIR}", str(item.directory))
    if item.plugin_root is not None:
        body = body.replace("${CLAUDE_PLUGIN_ROOT}", str(item.plugin_root))
    for i, val in enumerate(args.split()):
        body = body.replace(f"${i}", val)
    body = body.replace("$ARGUMENTS", args)
    return body
