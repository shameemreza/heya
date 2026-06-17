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


from heya.config import default_allowed_roots, load_allowed_roots


def test_default_allowed_roots_is_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    roots = default_allowed_roots()
    assert roots == (tmp_path.resolve(),)


def test_load_allowed_roots_defaults_to_cwd_when_no_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    roots = load_allowed_roots(config_path=tmp_path / "missing.toml")
    assert roots == (tmp_path.resolve(),)


def test_load_allowed_roots_reads_workspace_section(tmp_path):
    work = tmp_path / "projects"
    work.mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[workspace]\n"
        f'allowed_roots = ["{work}"]\n'
    )
    roots = load_allowed_roots(config_path=cfg)
    assert roots == (work.resolve(),)


def test_load_allowed_roots_expands_user(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[workspace]\n"
        'allowed_roots = ["~"]\n'
    )
    roots = load_allowed_roots(config_path=cfg)
    assert roots == (Path.home().resolve(),)


def test_load_allowed_roots_rejects_non_list(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[workspace]\n"
        'allowed_roots = "/just/a/string"\n'
    )
    with pytest.raises(ConfigError):
        load_allowed_roots(config_path=cfg)


def test_load_allowed_roots_rejects_non_string_entry(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[workspace]\n"
        'allowed_roots = [123]\n'
    )
    with pytest.raises(ConfigError):
        load_allowed_roots(config_path=cfg)


from heya.config import load_guidance_paths


def test_load_guidance_paths_empty_when_no_file(tmp_path):
    assert load_guidance_paths(config_path=tmp_path / "missing.toml") == ()


def test_load_guidance_paths_reads_guidance_section(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text("[guidance]\n" f'paths = ["{skills}"]\n')
    assert load_guidance_paths(config_path=cfg) == (skills.resolve(),)


def test_load_guidance_paths_expands_user(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[guidance]\n" 'paths = ["~"]\n')
    assert load_guidance_paths(config_path=cfg) == (Path.home().resolve(),)


def test_load_guidance_paths_rejects_non_list(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[guidance]\n" 'paths = "/just/a/string"\n')
    with pytest.raises(ConfigError):
        load_guidance_paths(config_path=cfg)


def test_load_guidance_paths_rejects_non_string_entry(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[guidance]\n" "paths = [123]\n")
    with pytest.raises(ConfigError):
        load_guidance_paths(config_path=cfg)


from heya.config import SearchConfig, load_search_config


def test_search_config_defaults_to_duckduckgo(tmp_path):
    cfg = load_search_config(config_path=tmp_path / "missing.toml")
    assert cfg.provider == "duckduckgo"
    assert cfg.api_key_env is None


def test_search_config_reads_section(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[search]\nprovider = "brave"\napi_key_env = "BRAVE_API_KEY"\n')
    cfg = load_search_config(config_path=cfg_file)
    assert cfg.provider == "brave"
    assert cfg.api_key_env == "BRAVE_API_KEY"


def test_search_config_api_key_reads_env(monkeypatch):
    monkeypatch.setenv("MY_SEARCH_KEY", "sk-123")
    cfg = SearchConfig(provider="tavily", api_key_env="MY_SEARCH_KEY")
    assert cfg.api_key == "sk-123"


def test_search_config_api_key_none_without_env():
    assert SearchConfig(provider="duckduckgo").api_key is None


def test_search_config_rejects_unknown_provider(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[search]\nprovider = "googol"\n')
    with pytest.raises(ConfigError):
        load_search_config(config_path=cfg_file)
