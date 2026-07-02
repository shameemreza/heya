import tomllib
from pathlib import Path


def _pyproject():
    return tomllib.loads(Path("pyproject.toml").read_text())


def test_keyring_in_mcp_extra():
    extras = _pyproject()["project"]["optional-dependencies"]
    assert any(dep.startswith("keyring") for dep in extras["mcp"])


def test_dev_extra_has_ruff():
    extras = _pyproject()["project"]["optional-dependencies"]
    assert any(dep.startswith("ruff") for dep in extras.get("dev", []))


def test_no_requirements_txt():
    assert not Path("requirements.txt").exists()
    assert not Path("requirements-dev.txt").exists()
