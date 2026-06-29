"""The landing page hero version is stamped from pyproject, not hand-edited."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "build_docs", ROOT / "site" / "build_docs.py")
build_docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_docs)  # works without `markdown`, which is lazy-imported


def test_read_version_matches_pyproject():
    version = build_docs.read_version()
    assert version
    # A simple semver-ish shape: dot-separated alphanumeric parts.
    assert all(part and part.replace("-", "").isalnum() for part in version.split("."))


def test_stamp_version_rewrites_the_hero_line():
    html = '<span class="t-dim">heya v0.0.1 · qwen2.5-coder:14b · local</span>'
    out = build_docs.stamp_version(html, "9.9.9")
    assert "heya v9.9.9 · qwen2.5-coder:14b · local" in out
    assert "v0.0.1" not in out


def test_stamp_version_is_idempotent():
    html = "heya v9.9.9 · local"
    once = build_docs.stamp_version(html, "9.9.9")
    twice = build_docs.stamp_version(once, "9.9.9")
    assert once == twice == html


def test_landing_hero_matches_pyproject_version():
    # The committed landing page should already carry the current version.
    version = build_docs.read_version()
    html = build_docs.SITE_INDEX.read_text(encoding="utf-8")
    assert f"heya v{version} " in html
