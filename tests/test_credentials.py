import os
import tomllib

from pathlib import Path

from heya.tomlw import dumps
from heya.credentials import save_key, load_key


def test_dumps_roundtrips_tables_and_lists():
    data = {
        "defaults": {"profile": "cloud"},
        "workspace": {"allowed_roots": ["~/a", "/b"]},
        "profiles": {
            "cloud": {"base_url": "https://x/v1", "model": "m", "context_window": 8192},
        },
    }
    parsed = tomllib.loads(dumps(data))
    assert parsed == data


def test_save_key_is_locked_and_roundtrips(tmp_path):
    p = tmp_path / "credentials.toml"
    save_key("cloud", "sk-secret", path=p)
    assert load_key("cloud", path=p) == "sk-secret"
    assert (p.stat().st_mode & 0o777) == 0o600


def test_save_key_preserves_other_profiles(tmp_path):
    p = tmp_path / "credentials.toml"
    save_key("a", "ka", path=p)
    save_key("b", "kb", path=p)
    assert load_key("a", path=p) == "ka"
    assert load_key("b", path=p) == "kb"


def test_load_key_absent_returns_none(tmp_path):
    assert load_key("nope", path=tmp_path / "credentials.toml") is None


def test_save_key_tightens_preexisting_loose_file(tmp_path):
    p = tmp_path / "credentials.toml"
    p.write_text('[old]\napi_key = "x"\n')
    p.chmod(0o644)
    save_key("cloud", "sk-new", path=p)
    assert (p.stat().st_mode & 0o777) == 0o600
    assert load_key("cloud", path=p) == "sk-new"
    assert load_key("old", path=p) == "x"  # other entries preserved
