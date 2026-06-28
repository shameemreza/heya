import io
import tomllib

from heya.init import run_init
from heya.credentials import load_key


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
