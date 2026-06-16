from pathlib import Path

import pytest

from heya.config import Profile, resolve_profile, ConfigError
from heya.config import BUILTIN_PROFILES, load_profiles


def test_profile_api_key_reads_named_env_var(monkeypatch):
    monkeypatch.setenv("MY_KEY", "secret-123")
    profile = Profile(name="p", base_url="http://x/v1", model="m", api_key_env="MY_KEY")
    assert profile.api_key == "secret-123"


def test_profile_api_key_is_none_without_env():
    profile = Profile(name="p", base_url="http://x/v1", model="m")
    assert profile.api_key is None


def test_resolve_explicit_name_wins(monkeypatch):
    monkeypatch.delenv("HEYA_PROFILE", raising=False)
    profiles = {"a": Profile("a", "http://a/v1", "ma"), "b": Profile("b", "http://b/v1", "mb")}
    assert resolve_profile("b", profiles=profiles).model == "mb"


def test_resolve_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("HEYA_PROFILE", "a")
    profiles = {"a": Profile("a", "http://a/v1", "ma")}
    assert resolve_profile(profiles=profiles).name == "a"


def test_resolve_unknown_profile_raises():
    profiles = {"a": Profile("a", "http://a/v1", "ma")}
    with pytest.raises(ConfigError) as exc:
        resolve_profile("nope", profiles=profiles)
    assert "nope" in str(exc.value)
    assert "a" in str(exc.value)


def test_builtin_profiles_include_local_default():
    assert "local" in BUILTIN_PROFILES
    local = BUILTIN_PROFILES["local"]
    assert local.base_url == "http://localhost:11434/v1"
    assert local.provider_type == "local"


def test_load_profiles_returns_builtins_when_no_file(tmp_path):
    profiles = load_profiles(config_path=tmp_path / "missing.toml")
    assert "local" in profiles


def test_load_profiles_merges_user_file(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[profiles.mybox]\n'
        'base_url = "http://192.168.1.9:11434/v1"\n'
        'model = "my-model"\n'
        'provider_type = "local"\n'
    )
    profiles = load_profiles(config_path=cfg)
    assert "local" in profiles  # builtins still present
    assert profiles["mybox"].model == "my-model"
    assert profiles["mybox"].base_url == "http://192.168.1.9:11434/v1"
