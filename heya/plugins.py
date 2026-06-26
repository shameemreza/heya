"""Discover Claude plugins and load their skills.

A plugin is a directory tree with a .claude-plugin/plugin.json and component
folders (skills/, agents/, commands/, hooks/). 13b loads SKILL.md skills from a
plugin's skills/ folder, namespaced 'plugin:skill', reusing heya/skills.py.
Discovery never raises (missing roots, bad manifests, deep trees are skipped)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .skills import SkillItem, collect_skills


@dataclass(frozen=True)
class Plugin:
    name: str
    root: Path
    description: str
    manifest: dict


def parse_plugin_manifest(text: str) -> dict:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def _find_manifests(root: Path, max_depth: int) -> list[Path]:
    """Return .claude-plugin/plugin.json paths under root, bounded by max_depth."""
    found: list[Path] = []
    root = Path(root)
    if not root.is_dir():
        return found

    def walk(d: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(d.iterdir())
        except OSError:
            return
        for entry in entries:
            if not entry.is_dir() or entry.is_symlink():
                continue
            if entry.name == ".claude-plugin":
                manifest = entry / "plugin.json"
                if manifest.is_file():
                    found.append(manifest)
            else:
                walk(entry, depth + 1)

    walk(root, 0)
    return found


def discover_plugins(roots: Sequence[Path], *, max_depth: int = 6) -> dict[str, Plugin]:
    """Map plugin name -> Plugin across roots. Later-found wins on a name collision
    (a higher version dir sorts later). Never raises."""
    plugins: dict[str, Plugin] = {}
    for root in roots:
        for manifest_path in _find_manifests(Path(root), max_depth):
            try:
                text = manifest_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            manifest = parse_plugin_manifest(text)
            plugin_root = manifest_path.parent.parent  # .claude-plugin/..
            name = manifest.get("name") or plugin_root.name
            plugins[name] = Plugin(
                name=name, root=plugin_root,
                description=str(manifest.get("description", ""))[:300],
                manifest=manifest,
            )
    return plugins


def plugin_skill_dirs(plugin: Plugin) -> list[Path]:
    """The plugin's skill directories: the default skills/ plus any manifest
    `skills` paths (string or list), relative to the plugin root. Existing only."""
    dirs: list[Path] = []
    default = plugin.root / "skills"
    if default.is_dir():
        dirs.append(default)
    raw = plugin.manifest.get("skills")
    extra = [raw] if isinstance(raw, str) else (raw if isinstance(raw, list) else [])
    for rel in extra:
        if not isinstance(rel, str):
            continue
        p = (plugin.root / rel).resolve() if not Path(rel).is_absolute() else Path(rel)
        if p.is_dir() and p not in dirs:
            dirs.append(p)
    return dirs


def collect_plugin_skills(plugins) -> dict[str, SkillItem]:
    """Collect every plugin's skills, namespaced 'plugin:skill' and carrying the
    plugin root for ${CLAUDE_PLUGIN_ROOT} substitution."""
    out: dict[str, SkillItem] = {}
    for plugin in plugins.values():
        dirs = plugin_skill_dirs(plugin)
        if not dirs:
            continue
        for skill_name, item in collect_skills(dirs).items():
            key = f"{plugin.name}:{skill_name}"
            out[key] = SkillItem(
                name=key, description=item.description, when_to_use=item.when_to_use,
                directory=item.directory, allowed_tools=item.allowed_tools,
                path=item.path, plugin_root=plugin.root,
            )
    return out
