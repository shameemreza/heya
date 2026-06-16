import pytest

from heya.config import Profile, resolve_profile, ConfigError


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
