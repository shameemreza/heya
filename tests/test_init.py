import io
import tomllib

from heya.credentials import load_key
from heya.init import run_init


def _run(answers, **kw):
    out = io.StringIO()
    code = run_init(stream=io.StringIO(answers), write=out.write, **kw)
    return code, out.getvalue()


def test_cloud_path_saves_key_and_writes_config(tmp_path):
    cfg = tmp_path / "config.toml"
    creds = tmp_path / "credentials.toml"
    # 1 = cloud, 1 = OpenRouter, then the key
    code, out = _run(
        "1\n1\nsk-paste\n",
        config_path=cfg, credentials_path=creds,
        verify=lambda profile, key: True,
    )
    assert code == 0
    assert load_key("cloud", path=creds) == "sk-paste"
    data = tomllib.loads(cfg.read_text())
    assert data["defaults"]["profile"] == "cloud"
    assert data["profiles"]["cloud"]["provider_type"] == "api_key"
    # the key is never written to config.toml
    assert "sk-paste" not in cfg.read_text()


def test_cloud_bad_key_reprompts_then_succeeds(tmp_path):
    cfg = tmp_path / "config.toml"
    creds = tmp_path / "credentials.toml"
    calls = {"n": 0}

    def verify(profile, key):
        calls["n"] += 1
        return key == "good"

    code, out = _run(
        "1\n1\nbad\ngood\n",
        config_path=cfg, credentials_path=creds, verify=verify,
    )
    assert code == 0 and calls["n"] == 2
    assert load_key("cloud", path=creds) == "good"


def test_local_path_pulls_after_consent(tmp_path):
    cfg = tmp_path / "config.toml"
    pulled = {"cmd": None}

    def runner(cmd):
        pulled["cmd"] = cmd
        return 0

    # 2 = local, model name (blank = default), y = consent to pull
    code, out = _run(
        "2\n\ny\n",
        config_path=cfg, runner=runner,
    )
    assert code == 0
    assert pulled["cmd"][:2] == ["ollama", "pull"]
    data = tomllib.loads(cfg.read_text())
    assert data["defaults"]["profile"] == "local"


def test_existing_config_requires_confirm(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[defaults]\nprofile = "local"\n')
    # answer n to the overwrite confirm -> abort with code 1
    code, out = _run("n\n", config_path=cfg)
    assert code == 1
    assert "n" not in tomllib.loads(cfg.read_text()).get("profiles", {})


def test_cloud_init_preserves_mcp_section(tmp_path):
    """Regression: heya init must not corrupt existing [mcp.servers.*] tables."""
    cfg = tmp_path / "config.toml"
    creds = tmp_path / "credentials.toml"
    # Write a config that has a real MCP section with nested headers inline table
    cfg.write_text(
        '[mcp.servers.linear]\n'
        'transport = "stdio"\n'
        'command = "npx"\n'
        'args = ["-y", "@linear/mcp-server"]\n'
        '[mcp.servers.linear.headers]\n'
        '"X-Tenant" = "acme"\n'
    )
    # y = update existing, 1 = cloud, 1 = OpenRouter, sk-test = key
    code, out = _run(
        "y\n1\n1\nsk-test\n",
        config_path=cfg, credentials_path=creds,
        verify=lambda profile, key: True,
    )
    assert code == 0
    data = tomllib.loads(cfg.read_text())
    # (a) MCP section survived intact
    assert data["mcp"]["servers"]["linear"]["command"] == "npx"
    assert data["mcp"]["servers"]["linear"]["headers"]["X-Tenant"] == "acme"
    # (b) defaults and profile are present and correct
    assert data["defaults"]["profile"] == "cloud"
    assert data["profiles"]["cloud"]["provider_type"] == "api_key"
    assert data["profiles"]["cloud"]["base_url"] == "https://openrouter.ai/api/v1"


def test_local_init_preserves_mcp_section(tmp_path):
    """Regression: heya init local path must not corrupt existing [mcp.servers.*] tables."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[mcp.servers.linear]\n'
        'transport = "stdio"\n'
        'command = "npx"\n'
        'args = ["-y", "@linear/mcp-server"]\n'
        '[mcp.servers.linear.headers]\n'
        '"X-Tenant" = "acme"\n'
    )
    # y = update existing, 2 = local, blank model (use default), n = skip pull
    code, out = _run(
        "y\n2\n\nn\n",
        config_path=cfg,
        runner=lambda cmd: 0,
    )
    assert code == 0
    data = tomllib.loads(cfg.read_text())
    # MCP section survived
    assert data["mcp"]["servers"]["linear"]["command"] == "npx"
    assert data["mcp"]["servers"]["linear"]["headers"]["X-Tenant"] == "acme"
    # Local profile is set
    assert data["defaults"]["profile"] == "local"
    assert data["profiles"]["local"]["provider_type"] == "local"
