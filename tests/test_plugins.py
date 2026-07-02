from pathlib import Path

from heya.plugins import (
    Plugin,
    collect_plugin_skills,
    discover_plugins,
    parse_plugin_manifest,
    plugin_skill_dirs,
)


def _make_plugin(root: Path, name: str, *, skills: dict[str, str] | None = None):
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "%s", "description": "the %s plugin"}' % (name, name))
    for skill_name, body in (skills or {}).items():
        sd = root / "skills" / skill_name
        sd.mkdir(parents=True)
        (sd / "SKILL.md").write_text(f"---\nname: {skill_name}\ndescription: {skill_name} desc\n---\n{body}")


def test_parse_plugin_manifest():
    assert parse_plugin_manifest('{"name": "p"}')["name"] == "p"
    assert parse_plugin_manifest("not json") == {}


def test_discover_plugins_nested(tmp_path):
    # Mirror the real cache layout: <root>/<marketplace>/<plugin>/<version>/.claude-plugin/
    deep = tmp_path / "cache" / "mkt" / "superpowers" / "1.0.0"
    _make_plugin(deep, "superpowers")
    plugins = discover_plugins([tmp_path])
    assert "superpowers" in plugins
    assert plugins["superpowers"].root == deep


def test_discover_plugins_skips_bad_and_missing(tmp_path):
    good = tmp_path / "good"
    _make_plugin(good, "good")
    bad = tmp_path / "bad" / ".claude-plugin"
    bad.mkdir(parents=True)
    (bad / "plugin.json").write_text("garbage{")  # bad manifest -> name falls back to dir
    plugins = discover_plugins([tmp_path, tmp_path / "does-not-exist"])
    assert "good" in plugins


def test_plugin_skill_dirs(tmp_path):
    root = tmp_path / "p"
    _make_plugin(root, "p", skills={"foo": "Body"})
    plug = Plugin("p", root, "d", {})
    dirs = plugin_skill_dirs(plug)
    assert (root / "skills") in dirs


def test_collect_plugin_skills_namespaced(tmp_path):
    root = tmp_path / "p"
    _make_plugin(root, "superpowers", skills={"brainstorming": "Think hard"})
    plugins = {"superpowers": Plugin("superpowers", root, "d", {})}
    skills = collect_plugin_skills(plugins)
    assert "superpowers:brainstorming" in skills
    assert skills["superpowers:brainstorming"].plugin_root == root


def test_discover_plugins_skips_symlinked_dirs(tmp_path):
    import os
    real = tmp_path / "real"
    (real / ".claude-plugin").mkdir(parents=True)
    (real / ".claude-plugin" / "plugin.json").write_text('{"name": "real"}')
    # A symlink loop: link -> tmp_path (its own ancestor). Must not hang or RecursionError.
    link = tmp_path / "loop"
    try:
        os.symlink(tmp_path, link)
    except (OSError, NotImplementedError):
        import pytest
        pytest.skip("symlinks not supported here")
    plugins = discover_plugins([tmp_path], max_depth=6)
    assert "real" in plugins  # completes without raising; symlinked dir skipped


def test_discover_does_not_recurse_into_plugin_subtree(tmp_path):
    root = tmp_path / "p"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text('{"name": "p"}')
    # A nested .claude-plugin deeper inside the plugin must be ignored (pruned).
    nested = root / "vendor" / "inner"
    (nested / ".claude-plugin").mkdir(parents=True)
    (nested / ".claude-plugin" / "plugin.json").write_text('{"name": "inner"}')
    plugins = discover_plugins([tmp_path])
    assert "p" in plugins
    assert "inner" not in plugins  # pruned: not descended into p's subtree
