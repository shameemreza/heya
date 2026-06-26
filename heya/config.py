"""Configuration: providers, profiles, and active-profile resolution.

The model is configuration, not architecture. A Profile fully describes how to
reach a model (endpoint, model id, auth, type). Profiles are switchable; nothing
in the agent assumes a specific model or runner.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT = 120.0
DEFAULT_PROFILE = "local"


class ConfigError(Exception):
    """Raised when configuration cannot be resolved."""


@dataclass(frozen=True)
class Profile:
    name: str
    base_url: str
    model: str
    provider_type: str = "local"  # "local" | "api_key" | "oauth"
    api_key_env: str | None = None  # env var NAME holding the key, never the key itself
    timeout: float = DEFAULT_TIMEOUT
    context_window: int = 32768

    @property
    def api_key(self) -> str | None:
        if self.api_key_env is None:
            return None
        return os.environ.get(self.api_key_env)


def resolve_profile(
    name: str | None = None,
    *,
    profiles: dict[str, Profile],
) -> Profile:
    """Resolve the active profile.

    Precedence: explicit name > HEYA_PROFILE env var > DEFAULT_PROFILE.
    """
    chosen = name or os.environ.get("HEYA_PROFILE") or DEFAULT_PROFILE
    if chosen not in profiles:
        available = ", ".join(sorted(profiles))
        raise ConfigError(f"Unknown profile {chosen!r}. Available: {available}")
    return profiles[chosen]


# Built-in presets. `local` is the reference default; users add or override
# their own in ~/.config/heya/config.toml. The cloud example shows that
# switching providers is config, not code.
BUILTIN_PROFILES: dict[str, Profile] = {
    "local": Profile(
        name="local",
        base_url="http://localhost:11434/v1",
        model="gemma4:12b",
        provider_type="local",
    ),
    "cloud-openrouter": Profile(
        name="cloud-openrouter",
        base_url="https://openrouter.ai/api/v1",
        model="openrouter/auto",  # user picks any model id OpenRouter exposes
        provider_type="api_key",
        api_key_env="OPENROUTER_API_KEY",
    ),
}


def default_config_path() -> Path:
    return Path.home() / ".config" / "heya" / "config.toml"


def default_allowed_roots() -> tuple[Path, ...]:
    """The working directory is the sole allowed root unless config widens it."""
    return (Path.cwd().resolve(),)


def load_allowed_roots(config_path: Path | None = None) -> tuple[Path, ...]:
    """Folders the file/command tools may operate within.

    User file shape:
        [workspace]
        allowed_roots = ["~/projects/foo", "/abs/path/bar"]

    Defaults to the current working directory when no config is present.
    """
    path = config_path or default_config_path()
    if not path.exists():
        return default_allowed_roots()
    data = tomllib.loads(path.read_text())
    raw = data.get("workspace", {}).get("allowed_roots")
    if not raw:
        return default_allowed_roots()
    if not isinstance(raw, list):
        raise ConfigError(
            f"workspace.allowed_roots must be a list of paths, got {type(raw).__name__}"
        )
    for entry in raw:
        if not isinstance(entry, str):
            raise ConfigError(
                f"workspace.allowed_roots entries must be strings, got {entry!r}"
            )
    return tuple(Path(p).expanduser().resolve() for p in raw)


def default_skill_paths() -> tuple[Path, ...]:
    """Where Heya looks for Claude SKILL.md skills, in precedence order (later
    wins on a name collision): the user's Claude dir, the project's Claude dir,
    and a Heya-native dir. Only existing directories matter; collect_skills skips
    the rest."""
    home = Path.home()
    return (
        home / ".claude" / "skills",
        Path.cwd() / ".claude" / "skills",
        home / ".config" / "heya" / "skills",
    )


def load_skill_paths(config_path: Path | None = None) -> tuple[Path, ...]:
    """Skill discovery directories.

    User file shape:
        [skills]
        enabled = true            # set false to disable skill discovery
        paths = ["~/x/skills"]    # replaces the defaults when given
    """
    path = config_path or default_config_path()
    if not path.exists():
        return default_skill_paths()
    data = tomllib.loads(path.read_text()).get("skills", {})
    if data.get("enabled") is False:
        return ()
    raw = data.get("paths")
    if not raw:
        return default_skill_paths()
    return tuple(Path(p).expanduser() for p in raw)


def default_plugin_paths() -> tuple[Path, ...]:
    home = Path.home()
    return (home / ".claude" / "plugins" / "cache", home / ".config" / "heya" / "plugins")


def load_plugin_paths(config_path: Path | None = None) -> tuple[Path, ...]:
    """Plugin discovery roots.

    User file shape:
        [plugins]
        enabled = true            # false disables plugin discovery
        paths = ["~/x/plugins"]   # replaces the defaults when given
        disabled = ["name", ...]  # drop specific plugins after discovery
    """
    path = config_path or default_config_path()
    if not path.exists():
        return default_plugin_paths()
    data = tomllib.loads(path.read_text()).get("plugins", {})
    if data.get("enabled") is False:
        return ()
    raw = data.get("paths")
    if not raw:
        return default_plugin_paths()
    return tuple(Path(p).expanduser() for p in raw)


def load_disabled_plugins(config_path: Path | None = None) -> frozenset[str]:
    path = config_path or default_config_path()
    if not path.exists():
        return frozenset()
    data = tomllib.loads(path.read_text()).get("plugins", {})
    raw = data.get("disabled") or []
    return frozenset(str(n) for n in raw if isinstance(n, str))


def load_guidance_paths(config_path: Path | None = None) -> tuple[Path, ...]:
    """User guidance folders the read_guidance tool searches, on top of the
    bundled baseline.

    User file shape:
        [guidance]
        paths = ["~/dotbrain/shared/skills", "/abs/team/guidance"]

    Defaults to no user folders (empty) when unset; the bundled baseline is
    added by the CLI, not here.
    """
    path = config_path or default_config_path()
    if not path.exists():
        return ()
    data = tomllib.loads(path.read_text())
    raw = data.get("guidance", {}).get("paths")
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise ConfigError(
            f"guidance.paths must be a list of paths, got {type(raw).__name__}"
        )
    for entry in raw:
        if not isinstance(entry, str):
            raise ConfigError(f"guidance.paths entries must be strings, got {entry!r}")
    return tuple(Path(p).expanduser().resolve() for p in raw)


KNOWN_SEARCH_PROVIDERS = frozenset({"duckduckgo", "brave", "tavily"})


@dataclass(frozen=True)
class SearchConfig:
    provider: str = "duckduckgo"
    api_key_env: str | None = None  # env var NAME holding the key, never the key

    @property
    def api_key(self) -> str | None:
        if self.api_key_env is None:
            return None
        return os.environ.get(self.api_key_env)


def load_search_config(config_path: Path | None = None) -> SearchConfig:
    """Web-search provider selection.

    User file shape:
        [search]
        provider = "brave"            # duckduckgo (default, keyless) | brave | tavily
        api_key_env = "BRAVE_API_KEY" # required for brave/tavily; never the key itself
    """
    path = config_path or default_config_path()
    if not path.exists():
        return SearchConfig()
    data = tomllib.loads(path.read_text())
    raw = data.get("search")
    if not raw:
        return SearchConfig()
    provider = raw.get("provider", "duckduckgo")
    if provider not in KNOWN_SEARCH_PROVIDERS:
        known = ", ".join(sorted(KNOWN_SEARCH_PROVIDERS))
        raise ConfigError(f"Unknown search provider {provider!r}. Known: {known}")
    return SearchConfig(provider=provider, api_key_env=raw.get("api_key_env"))


@dataclass(frozen=True)
class ContextConfig:
    threshold: float = 0.85
    reserve_tokens: int = 2048
    keep_recent_tokens: int = 4096
    task_token_budget: int = 200000


def load_context_config(config_path: Path | None = None) -> ContextConfig:
    """Context-management settings.

    User file shape:
        [context]
        threshold = 0.85           # compact at this fraction of the window
        reserve_tokens = 2048      # headroom for the reply + summary call
        keep_recent_tokens = 4096  # verbatim recent-tail budget
        task_token_budget = 200000 # per-task ceiling; 0 = unlimited
    """
    default = ContextConfig()
    path = config_path or default_config_path()
    if not path.exists():
        return default
    data = tomllib.loads(path.read_text()).get("context", {})
    return ContextConfig(
        threshold=float(data.get("threshold", default.threshold)),
        reserve_tokens=int(data.get("reserve_tokens", default.reserve_tokens)),
        keep_recent_tokens=int(data.get("keep_recent_tokens", default.keep_recent_tokens)),
        task_token_budget=int(data.get("task_token_budget", default.task_token_budget)),
    )


@dataclass(frozen=True)
class RoutingConfig:
    weak_profile: str | None = None


def load_routing_config(config_path: Path | None = None) -> RoutingConfig:
    """Model-routing settings.

    User file shape:
        [routing]
        weak_profile = "local-small"   # names an existing profile; optional

    The weak profile is an optional cheaper/smaller secondary model used for
    compaction summaries and explicitly-marked trivial sub-agent tasks. Unset
    means the feature is off (weak == main).
    """
    path = config_path or default_config_path()
    if not path.exists():
        return RoutingConfig()
    data = tomllib.loads(path.read_text()).get("routing", {})
    weak = data.get("weak_profile")
    return RoutingConfig(weak_profile=weak if weak else None)


def resolve_weak_profile(
    routing: RoutingConfig, profiles: dict[str, Profile]
) -> Profile | None:
    """Resolve the configured weak profile to a Profile, or None when unset.

    Raises ConfigError (fail fast, like resolve_profile) if a name is given but
    no profile matches it.
    """
    name = routing.weak_profile
    if name is None:
        return None
    if name not in profiles:
        available = ", ".join(sorted(profiles))
        raise ConfigError(
            f"Unknown weak_profile {name!r}. Available: {available}"
        )
    return profiles[name]


def load_browser_headless(config_path: Path | None = None) -> bool:
    """Whether the browser runs headless (default) or visibly.

    User file shape:
        [browser]
        headless = false   # watch the browser work; default true
    """
    path = config_path or default_config_path()
    if not path.exists():
        return True
    data = tomllib.loads(path.read_text())
    return bool(data.get("browser", {}).get("headless", True))


def load_wp_path(config_path: Path | None = None) -> Path | None:
    """Default WordPress root for the WP tools, if the user sets one.

    User file shape:
        [wordpress]
        path = "~/Herd/my-site"   # optional; tools also accept a per-call path

    Returns None when unset — the tools then use a per-call path or the cwd.
    """
    path = config_path or default_config_path()
    if not path.exists():
        return None
    data = tomllib.loads(path.read_text())
    raw = data.get("wordpress", {}).get("path")
    if not raw:
        return None
    if not isinstance(raw, str):
        raise ConfigError(f"wordpress.path must be a string, got {type(raw).__name__}")
    return Path(raw).expanduser().resolve()


def load_memory_path(config_path: Path | None = None) -> Path:
    """Folder for Heya's long-term memory files.

    User file shape:
        [memory]
        path = "~/somewhere/heya-memory"   # optional

    Defaults to ~/.config/heya/memory.
    """
    default = Path.home() / ".config" / "heya" / "memory"
    path = config_path or default_config_path()
    if not path.exists():
        return default
    data = tomllib.loads(path.read_text())
    raw = data.get("memory", {}).get("path")
    if not raw:
        return default
    if not isinstance(raw, str):
        raise ConfigError(f"memory.path must be a string, got {type(raw).__name__}")
    return Path(raw).expanduser().resolve()


def load_approval_allow(config_path: Path | None = None) -> tuple[str, ...]:
    """Command prefixes that auto-approve, skipping the gate (fail-closed).

    User file shape:
        [approval]
        allow = ["wp plugin list", "wp option get", "git status"]

    A gated command auto-approves only when it starts with one of these. No
    denylist — anything not listed still prompts. Defaults to none.
    """
    path = config_path or default_config_path()
    if not path.exists():
        return ()
    data = tomllib.loads(path.read_text())
    raw = data.get("approval", {}).get("allow")
    if not raw:
        return ()
    if not isinstance(raw, list) or not all(isinstance(e, str) for e in raw):
        raise ConfigError("approval.allow must be a list of strings.")
    return tuple(raw)


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command: str = ""
    transport: str = "stdio"
    args: tuple[str, ...] = ()
    env_keys: tuple[str, ...] = ()
    enabled: bool = True
    tools: tuple[str, ...] = ("*",)
    url: str = ""
    auth_token_env: str | None = None
    headers: tuple[tuple[str, str], ...] = ()
    tls_verify: bool = True
    tls_ca_cert: str | None = None
    tls_client_cert: str | None = None
    tls_client_key: str | None = None
    auth: str = "none"
    scopes: tuple[str, ...] = ()
    oauth_client_name: str | None = None
    oauth_token_store: str = "keyring"


_VALID_TRANSPORTS = ("stdio", "http", "sse")
_VALID_AUTH = ("none", "bearer", "oauth")
_VALID_TOKEN_STORE = ("keyring", "memory")


def _headers_pairs(value, *, field: str) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise ConfigError(f"mcp.servers.{field} must be a table of string values.")
    return tuple(value.items())


def _opt_str(value, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"mcp.servers.{field} must be a string.")
    return value


def _str_tuple(value, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(e, str) for e in value):
        raise ConfigError(f"mcp.servers.{field} must be a list of strings.")
    return tuple(value)


def load_mcp_servers(config_path: Path | None = None) -> tuple[MCPServerConfig, ...]:
    """MCP servers Heya may connect to.

    User file shape:
        [mcp.servers.<name>]
        transport = "stdio"          # stdio | http | sse
        command   = "npx"            # required for stdio; optional for http/sse
        args      = ["-y", "some-mcp-server"]
        env_keys  = ["SOME_TOKEN"]   # env var NAMES; values injected at spawn, never stored
        enabled   = true             # default true
        tools     = ["*"]            # "*" = all, or an explicit allowlist
        url       = "https://..."    # required for http/sse
        auth_token_env = "MY_TOKEN"  # env var NAME holding a bearer token
        headers   = { "X-Tenant" = "acme" }  # extra request headers (string→string)
        tls_verify     = true        # set false to skip TLS verification
        tls_ca_cert    = "~/ca.pem"  # custom CA bundle path
        tls_client_cert = "~/c.pem"  # mTLS client cert (requires tls_client_key)
        tls_client_key  = "~/c.key"  # mTLS client private key

    Defaults to no servers when the file or [mcp] section is absent.
    """
    path = config_path or default_config_path()
    if not path.exists():
        return ()
    data = tomllib.loads(path.read_text())
    raw_servers = data.get("mcp", {}).get("servers", {})
    servers: list[MCPServerConfig] = []
    for name, raw in raw_servers.items():
        transport = raw.get("transport", "stdio")
        if transport not in _VALID_TRANSPORTS:
            allowed = ", ".join(_VALID_TRANSPORTS)
            raise ConfigError(
                f"mcp.servers.{name}.transport {transport!r} is invalid; allowed: {allowed}."
            )
        command = raw.get("command", "")
        url = raw.get("url", "")
        if transport == "stdio":
            if not isinstance(command, str) or not command:
                raise ConfigError(f"mcp.servers.{name}.command is required for stdio and must be a string.")
        else:  # http / sse
            if not isinstance(url, str) or not url:
                raise ConfigError(f"mcp.servers.{name}.url is required for {transport} and must be a string.")
            command = command if isinstance(command, str) else ""
        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"mcp.servers.{name}.enabled must be a boolean.")
        tls_verify = raw.get("tls_verify", True)
        if not isinstance(tls_verify, bool):
            raise ConfigError(f"mcp.servers.{name}.tls_verify must be a boolean.")
        tls_client_cert = _opt_str(raw.get("tls_client_cert"), field=f"{name}.tls_client_cert")
        tls_client_key = _opt_str(raw.get("tls_client_key"), field=f"{name}.tls_client_key")
        if tls_client_cert and not tls_client_key:
            raise ConfigError(f"mcp.servers.{name}.tls_client_cert requires tls_client_key (mTLS needs both).")
        auth_token_env = _opt_str(raw.get("auth_token_env"), field=f"{name}.auth_token_env")
        auth = raw.get("auth")
        if auth is None:
            auth = "bearer" if auth_token_env else "none"
        if auth not in _VALID_AUTH:
            raise ConfigError(f"mcp.servers.{name}.auth {auth!r} is invalid; allowed: {', '.join(_VALID_AUTH)}.")
        if auth == "oauth":
            if transport not in ("http", "sse"):
                raise ConfigError(f"mcp.servers.{name}.auth = \"oauth\" requires an http or sse transport.")
            if auth_token_env:
                raise ConfigError(f"mcp.servers.{name}: auth = \"oauth\" and auth_token_env are mutually exclusive.")
        token_store = raw.get("oauth_token_store", "keyring")
        if token_store not in _VALID_TOKEN_STORE:
            raise ConfigError(f"mcp.servers.{name}.oauth_token_store {token_store!r} is invalid; allowed: {', '.join(_VALID_TOKEN_STORE)}.")
        tools_raw = raw.get("tools")
        tools = _str_tuple(tools_raw, field=f"{name}.tools") if tools_raw is not None else ("*",)
        servers.append(MCPServerConfig(
            name=name, command=command, transport=transport,
            args=_str_tuple(raw.get("args"), field=f"{name}.args"),
            env_keys=_str_tuple(raw.get("env_keys"), field=f"{name}.env_keys"),
            enabled=enabled, tools=tools,
            url=url,
            auth_token_env=auth_token_env,
            headers=_headers_pairs(raw.get("headers"), field=f"{name}.headers"),
            tls_verify=tls_verify,
            tls_ca_cert=_opt_str(raw.get("tls_ca_cert"), field=f"{name}.tls_ca_cert"),
            tls_client_cert=tls_client_cert, tls_client_key=tls_client_key,
            auth=auth,
            scopes=_str_tuple(raw.get("scopes"), field=f"{name}.scopes"),
            oauth_client_name=_opt_str(raw.get("oauth_client_name"), field=f"{name}.oauth_client_name"),
            oauth_token_store=token_store,
        ))
    return tuple(servers)


def load_hooks_config(config_path: Path | None = None) -> tuple[bool, tuple[Path, ...]]:
    """Lifecycle hooks. OFF by default — hooks execute shell.

    User file shape:
        [hooks]
        enabled = true                      # default false
        sources = ["~/.config/heya/hooks.json"]   # replaces the defaults
    """
    home = Path.home()
    default_sources = (
        home / ".claude" / "settings.json",
        Path.cwd() / ".claude" / "settings.json",
        home / ".config" / "heya" / "hooks.json",
    )
    path = config_path or default_config_path()
    if not path.exists():
        return (False, default_sources)
    data = tomllib.loads(path.read_text()).get("hooks", {})
    enabled = data.get("enabled") is True
    raw = data.get("sources")
    if raw:
        sources = tuple(Path(p).expanduser() for p in raw)
    else:
        sources = default_sources
    return (enabled, sources)


def load_profiles(config_path: Path | None = None) -> dict[str, Profile]:
    """Built-in profiles merged with any user-defined ones from a TOML file.

    User file shape:
        [profiles.<name>]
        base_url = "..."
        model = "..."
        provider_type = "local" | "api_key" | "oauth"
        api_key_env = "SOME_ENV_VAR"   # optional
        context_window = 32768         # optional; per-model context window override
    """
    profiles = dict(BUILTIN_PROFILES)
    path = config_path or default_config_path()
    if path.exists():
        data = tomllib.loads(path.read_text())
        for name, raw in data.get("profiles", {}).items():
            profiles[name] = Profile(name=name, **raw)
    return profiles
