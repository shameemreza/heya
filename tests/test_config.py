from pathlib import Path

import pytest

from heya.config import Profile, resolve_profile, ConfigError
from heya.config import BUILTIN_PROFILES, load_profiles
from heya.config import MCPServerConfig, load_mcp_servers


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


from heya.config import load_browser_headless


def test_browser_headless_defaults_true(tmp_path):
    assert load_browser_headless(config_path=tmp_path / "missing.toml") is True


def test_browser_headless_can_be_disabled(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[browser]\nheadless = false\n")
    assert load_browser_headless(config_path=cfg) is False


def test_load_wp_path_reads_wordpress_section(tmp_path):
    from heya.config import load_wp_path
    cfg = tmp_path / "config.toml"
    cfg.write_text('[wordpress]\npath = "~/Herd/site"\n')
    assert str(load_wp_path(cfg)).endswith("Herd/site")


def test_load_wp_path_absent_is_none(tmp_path):
    from heya.config import load_wp_path
    assert load_wp_path(tmp_path / "missing.toml") is None


def test_load_approval_allow_reads_list(tmp_path):
    from heya.config import load_approval_allow
    cfg = tmp_path / "config.toml"
    cfg.write_text('[approval]\nallow = ["wp plugin list", "wp option get"]\n')
    assert load_approval_allow(cfg) == ("wp plugin list", "wp option get")


def test_load_approval_allow_absent_is_empty(tmp_path):
    from heya.config import load_approval_allow
    assert load_approval_allow(tmp_path / "missing.toml") == ()


def _write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text)
    return p


def test_load_mcp_servers_absent_returns_empty(tmp_path):
    assert load_mcp_servers(tmp_path / "missing.toml") == ()


def test_load_mcp_servers_no_section_returns_empty(tmp_path):
    p = _write(tmp_path, "[workspace]\nallowed_roots = []\n")
    assert load_mcp_servers(p) == ()


def test_load_mcp_servers_parses_entry_with_defaults(tmp_path):
    p = _write(tmp_path, (
        '[mcp.servers.demo]\n'
        'transport = "stdio"\n'
        'command = "npx"\n'
        'args = ["-y", "demo-server"]\n'
        'env_keys = ["DEMO_TOKEN"]\n'
    ))
    (server,) = load_mcp_servers(p)
    assert server == MCPServerConfig(
        name="demo", transport="stdio", command="npx",
        args=("-y", "demo-server"), env_keys=("DEMO_TOKEN",),
        enabled=True, tools=("*",),
    )


def test_load_mcp_servers_respects_enabled_and_tools(tmp_path):
    p = _write(tmp_path, (
        '[mcp.servers.demo]\n'
        'command = "x"\n'
        'enabled = false\n'
        'tools = ["a", "b"]\n'
    ))
    (server,) = load_mcp_servers(p)
    assert server.enabled is False
    assert server.tools == ("a", "b")
    assert server.transport == "stdio"  # default
    assert server.args == () and server.env_keys == ()


def test_load_mcp_servers_rejects_unknown_transport(tmp_path):
    # "http" is now valid; use a genuinely unknown transport to exercise the guard
    p = _write(tmp_path, '[mcp.servers.demo]\ncommand = "x"\ntransport = "ws"\nurl = "wss://x"\n')
    with pytest.raises(ConfigError) as exc:
        load_mcp_servers(p)
    assert "ws" in str(exc.value) and "stdio" in str(exc.value)


def test_load_mcp_servers_requires_command(tmp_path):
    p = _write(tmp_path, '[mcp.servers.demo]\ntransport = "stdio"\n')
    with pytest.raises(ConfigError):
        load_mcp_servers(p)


def test_load_mcp_servers_rejects_non_string_list_entries(tmp_path):
    p = _write(tmp_path, '[mcp.servers.demo]\ncommand = "x"\nargs = [1, 2]\n')
    with pytest.raises(ConfigError):
        load_mcp_servers(p)


def test_load_mcp_http_server_parses(tmp_path):
    p = _write(tmp_path, (
        '[mcp.servers.hosted]\n'
        'transport = "http"\n'
        'url = "https://mcp.example.com/mcp"\n'
        'auth_token_env = "EXAMPLE_TOKEN"\n'
        'headers = { "X-Tenant" = "acme" }\n'
    ))
    (s,) = load_mcp_servers(p)
    assert s.transport == "http"
    assert s.url == "https://mcp.example.com/mcp"
    assert s.auth_token_env == "EXAMPLE_TOKEN"
    assert s.headers == (("X-Tenant", "acme"),)
    assert s.command == ""  # optional for http


def test_load_mcp_sse_server_parses(tmp_path):
    p = _write(tmp_path, '[mcp.servers.legacy]\ntransport = "sse"\nurl = "https://old/sse"\n')
    (s,) = load_mcp_servers(p)
    assert s.transport == "sse" and s.url == "https://old/sse"


def test_load_mcp_http_requires_url(tmp_path):
    p = _write(tmp_path, '[mcp.servers.h]\ntransport = "http"\n')
    with pytest.raises(ConfigError) as exc:
        load_mcp_servers(p)
    assert "url" in str(exc.value)


def test_load_mcp_stdio_still_requires_command(tmp_path):
    p = _write(tmp_path, '[mcp.servers.s]\ntransport = "stdio"\n')
    with pytest.raises(ConfigError) as exc:
        load_mcp_servers(p)
    assert "command" in str(exc.value)


def test_load_mcp_unknown_transport_rejected(tmp_path):
    p = _write(tmp_path, '[mcp.servers.x]\ntransport = "ws"\nurl = "wss://x"\n')
    with pytest.raises(ConfigError) as exc:
        load_mcp_servers(p)
    assert "ws" in str(exc.value) and "stdio" in str(exc.value)


def test_load_mcp_tls_fields_parse(tmp_path):
    p = _write(tmp_path, (
        '[mcp.servers.corp]\n'
        'transport = "http"\n'
        'url = "https://corp/mcp"\n'
        'tls_verify = false\n'
        'tls_ca_cert = "~/ca.pem"\n'
        'tls_client_cert = "~/c.pem"\n'
        'tls_client_key = "~/c.key"\n'
    ))
    (s,) = load_mcp_servers(p)
    assert s.tls_verify is False
    assert s.tls_ca_cert == "~/ca.pem"
    assert s.tls_client_cert == "~/c.pem" and s.tls_client_key == "~/c.key"


def test_load_mcp_mtls_cert_requires_key(tmp_path):
    p = _write(tmp_path, (
        '[mcp.servers.corp]\ntransport = "http"\nurl = "https://corp/mcp"\n'
        'tls_client_cert = "~/c.pem"\n'  # no key
    ))
    with pytest.raises(ConfigError) as exc:
        load_mcp_servers(p)
    assert "tls_client_key" in str(exc.value)


def test_load_mcp_headers_must_be_string_table(tmp_path):
    p = _write(tmp_path, '[mcp.servers.h]\ntransport = "http"\nurl = "https://h"\nheaders = { X = 1 }\n')
    with pytest.raises(ConfigError):
        load_mcp_servers(p)


def test_load_mcp_oauth_server_parses(tmp_path):
    p = _write(tmp_path, (
        '[mcp.servers.o]\n'
        'transport = "http"\n'
        'url = "https://o/mcp"\n'
        'auth = "oauth"\n'
        'scopes = ["mcp:read", "mcp:write"]\n'
        'oauth_client_name = "Heya"\n'
    ))
    (s,) = load_mcp_servers(p)
    assert s.auth == "oauth"
    assert s.scopes == ("mcp:read", "mcp:write")
    assert s.oauth_client_name == "Heya"
    assert s.oauth_token_store == "keyring"  # default


def test_load_mcp_auth_inferred_bearer_from_token_env(tmp_path):
    p = _write(tmp_path, '[mcp.servers.b]\ntransport = "http"\nurl = "https://b"\nauth_token_env = "T"\n')
    (s,) = load_mcp_servers(p)
    assert s.auth == "bearer"  # inferred


def test_load_mcp_auth_defaults_none(tmp_path):
    p = _write(tmp_path, '[mcp.servers.n]\ntransport = "http"\nurl = "https://n"\n')
    (s,) = load_mcp_servers(p)
    assert s.auth == "none"


def test_load_mcp_oauth_on_stdio_rejected(tmp_path):
    p = _write(tmp_path, '[mcp.servers.x]\ncommand = "y"\nauth = "oauth"\n')
    with pytest.raises(ConfigError) as exc:
        load_mcp_servers(p)
    assert "oauth" in str(exc.value).lower()


def test_load_mcp_oauth_with_token_env_rejected(tmp_path):
    p = _write(tmp_path, (
        '[mcp.servers.x]\ntransport = "http"\nurl = "https://x"\n'
        'auth = "oauth"\nauth_token_env = "T"\n'
    ))
    with pytest.raises(ConfigError) as exc:
        load_mcp_servers(p)
    assert "mutually exclusive" in str(exc.value).lower() or "auth_token_env" in str(exc.value)


def test_load_mcp_bad_auth_enum_rejected(tmp_path):
    p = _write(tmp_path, '[mcp.servers.x]\ntransport = "http"\nurl = "https://x"\nauth = "magic"\n')
    with pytest.raises(ConfigError):
        load_mcp_servers(p)


def test_load_mcp_bad_token_store_rejected(tmp_path):
    p = _write(tmp_path, (
        '[mcp.servers.x]\ntransport = "http"\nurl = "https://x"\n'
        'auth = "oauth"\noauth_token_store = "disk"\n'
    ))
    with pytest.raises(ConfigError):
        load_mcp_servers(p)


from heya.config import load_memory_path


def test_load_memory_path_default_when_unset(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[workspace]\nallowed_roots = []\n")
    assert load_memory_path(cfg) == Path.home() / ".config" / "heya" / "memory"


def test_load_memory_path_default_when_no_config(tmp_path):
    assert load_memory_path(tmp_path / "missing.toml") == Path.home() / ".config" / "heya" / "memory"


def test_load_memory_path_override(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[memory]\npath = "~/custom-mem"\n')
    assert load_memory_path(cfg) == (Path.home() / "custom-mem").resolve()


def test_load_memory_path_bad_type(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[memory]\npath = 5\n")
    try:
        load_memory_path(cfg)
        assert False, "expected ConfigError"
    except ConfigError:
        pass


from heya.config import ContextConfig, load_context_config


def test_profile_has_context_window_default():
    p = Profile(name="t", base_url="u", model="m")
    assert p.context_window == 32768


def test_load_context_config_defaults(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[workspace]\nallowed_roots = []\n")
    c = load_context_config(cfg)
    assert c == ContextConfig(threshold=0.85, reserve_tokens=2048,
                              keep_recent_tokens=4096, task_token_budget=200000)


def test_load_context_config_overrides(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[context]\nthreshold = 0.7\ntask_token_budget = 0\n")
    c = load_context_config(cfg)
    assert c.threshold == 0.7
    assert c.task_token_budget == 0           # unlimited
    assert c.reserve_tokens == 2048           # unset → default


def test_load_context_config_no_file(tmp_path):
    c = load_context_config(tmp_path / "missing.toml")
    assert c == ContextConfig(0.85, 2048, 4096, 200000)


from heya.config import default_plugin_paths, load_plugin_paths, load_disabled_plugins


def test_default_plugin_paths_includes_claude_cache():
    assert any(str(p).endswith(".claude/plugins/cache") for p in default_plugin_paths())


def test_load_plugin_paths_disabled(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[plugins]\nenabled = false\n")
    assert load_plugin_paths(p) == ()


def test_load_plugin_paths_explicit(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[plugins]\npaths = ["/abs/plugins"]\n')
    assert str(load_plugin_paths(p)[0]) == "/abs/plugins"


def test_load_disabled_plugins(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[plugins]\ndisabled = ["foo", "bar"]\n')
    assert load_disabled_plugins(p) == frozenset({"foo", "bar"})
    assert load_disabled_plugins(tmp_path / "none.toml") == frozenset()


from heya.config import default_skill_paths, load_skill_paths


def test_default_skill_paths_includes_claude_dir():
    paths = default_skill_paths()
    assert any(str(p).endswith(".claude/skills") for p in paths)


def test_load_skill_paths_absent_file_defaults(tmp_path):
    assert load_skill_paths(tmp_path / "nope.toml") == default_skill_paths()


def test_load_skill_paths_disabled(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[skills]\nenabled = false\n")
    assert load_skill_paths(p) == ()


def test_load_skill_paths_explicit(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[skills]\npaths = ["~/x/skills", "/abs/skills"]\n')
    out = load_skill_paths(p)
    assert len(out) == 2
    assert str(out[1]) == "/abs/skills"


from heya.config import load_hooks_config


def test_load_hooks_config_default_disabled(tmp_path):
    enabled, sources = load_hooks_config(tmp_path / "nope.toml")
    assert enabled is False
    assert any(str(s).endswith(".claude/settings.json") for s in sources)


def test_load_hooks_config_enabled(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[hooks]\nenabled = true\n")
    enabled, _ = load_hooks_config(p)
    assert enabled is True


def test_load_hooks_config_explicit_sources(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[hooks]\nenabled = true\nsources = ["/abs/hooks.json"]\n')
    enabled, sources = load_hooks_config(p)
    assert enabled is True and str(sources[0]) == "/abs/hooks.json"


from heya.config import (
    RoutingConfig, load_routing_config, resolve_weak_profile,
)


def _profiles():
    return {
        "main": Profile(name="main", base_url="http://x/v1", model="big"),
        "small": Profile(name="small", base_url="http://x/v1", model="tiny"),
    }


def test_load_routing_config_absent_file(tmp_path):
    cfg = load_routing_config(tmp_path / "nope.toml")
    assert cfg == RoutingConfig(weak_profile=None)


def test_load_routing_config_reads_block(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[routing]\nweak_profile = "small"\n')
    assert load_routing_config(p) == RoutingConfig(weak_profile="small")


def test_load_routing_config_no_block(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[workspace]\nallowed_roots = ["/tmp"]\n')
    assert load_routing_config(p) == RoutingConfig(weak_profile=None)


def test_resolve_weak_profile_unset_returns_none():
    assert resolve_weak_profile(RoutingConfig(None), _profiles()) is None


def test_resolve_weak_profile_named_returns_profile():
    prof = resolve_weak_profile(RoutingConfig("small"), _profiles())
    assert prof is not None and prof.name == "small" and prof.model == "tiny"


def test_resolve_weak_profile_unknown_raises():
    with pytest.raises(ConfigError) as exc:
        resolve_weak_profile(RoutingConfig("ghost"), _profiles())
    assert "ghost" in str(exc.value)


from heya.config import default_command_paths, load_command_paths, default_agent_paths, load_agent_paths


def test_default_command_and_agent_paths_include_claude_dirs():
    assert any(str(p).endswith(".claude/commands") for p in default_command_paths())
    assert any(str(p).endswith(".claude/agents") for p in default_agent_paths())


def test_load_command_paths_explicit(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[commands]\npaths = ["/abs/cmds"]\n')
    assert str(load_command_paths(p)[0]) == "/abs/cmds"


def test_load_agent_paths_disabled(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[agents]\nenabled = false\n")
    assert load_agent_paths(p) == ()


from heya.config import Identity, load_identity, build_identity_block


def test_load_identity_absent(tmp_path):
    assert load_identity(tmp_path / "nope.toml") == Identity()


def test_load_identity_reads_block(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[identity]\nname = "Shameem Reza"\nrole = "WooCommerce Happiness Engineer"\n')
    ident = load_identity(p)
    assert ident.name == "Shameem Reza" and ident.role == "WooCommerce Happiness Engineer"


def test_build_identity_block_empty_and_set():
    assert build_identity_block(Identity()) == ""
    block = build_identity_block(Identity(name="Sam", role="HE"))
    assert "Sam" in block and "HE" in block
    assert "writing-voice" in block  # nudges the default voice


def test_config_example_parses():
    import tomllib
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "config.example.toml").read_text()
    data = tomllib.loads(text)
    for block in ("identity", "skills", "plugins", "hooks", "context", "routing"):
        assert block in data


def test_resolve_api_key_prefers_env_then_file(tmp_path, monkeypatch):
    from heya.config import resolve_api_key
    from heya.config import Profile
    from heya.credentials import save_key
    creds = tmp_path / "credentials.toml"
    prof = Profile(name="cloud", base_url="u", model="m",
                   provider_type="api_key", api_key_env="HEYA_TEST_KEY")
    # file only
    save_key("cloud", "from-file", path=creds)
    monkeypatch.delenv("HEYA_TEST_KEY", raising=False)
    assert resolve_api_key(prof, credentials_path=creds) == "from-file"
    # env wins
    monkeypatch.setenv("HEYA_TEST_KEY", "from-env")
    assert resolve_api_key(prof, credentials_path=creds) == "from-env"


def test_resolve_api_key_none_when_nothing(tmp_path, monkeypatch):
    from heya.config import resolve_api_key, Profile
    monkeypatch.delenv("HEYA_TEST_KEY", raising=False)
    prof = Profile(name="cloud", base_url="u", model="m",
                   provider_type="api_key", api_key_env="HEYA_TEST_KEY")
    assert resolve_api_key(prof, credentials_path=tmp_path / "x.toml") is None


def test_write_config_roundtrips(tmp_path):
    import tomllib
    from heya.config import write_config
    p = tmp_path / "config.toml"
    data = {"defaults": {"profile": "cloud"},
            "profiles": {"cloud": {"base_url": "u", "model": "m", "provider_type": "api_key"}}}
    write_config(data, p)
    assert tomllib.loads(p.read_text()) == data


def test_load_default_profile(tmp_path):
    from heya.config import write_config, load_default_profile
    p = tmp_path / "config.toml"
    write_config({"defaults": {"profile": "cloud"}}, p)
    assert load_default_profile(p) == "cloud"
    assert load_default_profile(tmp_path / "missing.toml") is None


def test_resolve_profile_uses_default_then_builtin(monkeypatch):
    from heya.config import resolve_profile, BUILTIN_PROFILES
    monkeypatch.delenv("HEYA_PROFILE", raising=False)
    profiles = dict(BUILTIN_PROFILES)
    assert resolve_profile(None, profiles=profiles, default="cloud-openrouter").name == "cloud-openrouter"
    assert resolve_profile(None, profiles=profiles, default=None).name == "local"
    assert resolve_profile("local", profiles=profiles, default="cloud-openrouter").name == "local"


from heya.config import upsert_profile
import tomllib as _tomllib


def test_upsert_profile_creates_fresh_file(tmp_path):
    cfg = tmp_path / "config.toml"
    upsert_profile(cfg, "cloud", {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openrouter/auto",
        "provider_type": "api_key",
        "api_key_env": "OPENROUTER_API_KEY",
    })
    assert cfg.exists()
    data = _tomllib.loads(cfg.read_text())
    assert data["defaults"]["profile"] == "cloud"
    assert data["profiles"]["cloud"]["base_url"] == "https://openrouter.ai/api/v1"
    assert data["profiles"]["cloud"]["model"] == "openrouter/auto"
    assert data["profiles"]["cloud"]["api_key_env"] == "OPENROUTER_API_KEY"


def test_upsert_profile_creates_parent_dirs(tmp_path):
    cfg = tmp_path / "sub" / "dir" / "config.toml"
    upsert_profile(cfg, "local", {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5-coder:14b",
        "provider_type": "local",
    })
    assert cfg.exists()
    data = _tomllib.loads(cfg.read_text())
    assert data["defaults"]["profile"] == "local"


def test_upsert_profile_preserves_mcp_section(tmp_path):
    cfg = tmp_path / "config.toml"
    original = (
        '[mcp.servers.linear]\n'
        'transport = "stdio"\n'
        'command = "npx"\n'
        'args = ["-y", "@linear/mcp-server"]\n'
        '[mcp.servers.linear.headers]\n'
        '"X-Tenant" = "acme"\n'
    )
    cfg.write_text(original)
    upsert_profile(cfg, "cloud", {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "provider_type": "api_key",
        "api_key_env": "OPENAI_API_KEY",
    })
    data = _tomllib.loads(cfg.read_text())
    # MCP section intact
    assert data["mcp"]["servers"]["linear"]["command"] == "npx"
    assert data["mcp"]["servers"]["linear"]["headers"]["X-Tenant"] == "acme"
    # New profile is present
    assert data["defaults"]["profile"] == "cloud"
    assert data["profiles"]["cloud"]["provider_type"] == "api_key"


def test_upsert_profile_replaces_existing_profile(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[defaults]\nprofile = "cloud"\n\n'
        '[profiles.cloud]\n'
        'base_url = "https://old.example.com/v1"\n'
        'model = "old-model"\n'
        'provider_type = "api_key"\n'
        'api_key_env = "OLD_KEY"\n'
    )
    upsert_profile(cfg, "cloud", {
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-haiku-4-5",
        "provider_type": "api_key",
        "api_key_env": "ANTHROPIC_API_KEY",
    })
    data = _tomllib.loads(cfg.read_text())
    assert data["profiles"]["cloud"]["base_url"] == "https://api.anthropic.com/v1"
    assert data["profiles"]["cloud"]["model"] == "claude-haiku-4-5"
    assert data["profiles"]["cloud"]["api_key_env"] == "ANTHROPIC_API_KEY"
    # No stale values
    assert "old-model" not in cfg.read_text()


def test_upsert_profile_make_default_false_skips_defaults(tmp_path):
    cfg = tmp_path / "config.toml"
    upsert_profile(cfg, "cloud", {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "provider_type": "api_key",
    }, make_default=False)
    data = _tomllib.loads(cfg.read_text())
    assert "defaults" not in data
    assert data["profiles"]["cloud"]["model"] == "gpt-4o-mini"


def test_model_supports_vision():
    from heya.config import Profile, model_supports_vision
    assert model_supports_vision(Profile(name="c", base_url="u", model="gpt-4o")) is True
    assert model_supports_vision(Profile(name="c", base_url="u", model="claude-haiku-4-5")) is True
    assert model_supports_vision(Profile(name="l", base_url="u", model="llama3.2-vision")) is True
    assert model_supports_vision(Profile(name="l", base_url="u", model="qwen2.5-coder:14b")) is False
    # explicit flag overrides the heuristic
    assert model_supports_vision(Profile(name="l", base_url="u", model="mystery", vision=True)) is True


from heya.config import AgentConfig, load_agent_config


def test_agent_config_default(tmp_path):
    cfg = load_agent_config(tmp_path / "missing.toml")
    assert cfg == AgentConfig(max_background=4)


def test_agent_config_reads_max_background(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[agents]\nmax_background = 8\n")
    assert load_agent_config(p).max_background == 8
