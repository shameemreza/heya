import io

from heya.config import load_wordpress_config
from heya.credentials import load_key
from heya.wpconnect import run_wp_connect


def test_wp_connect_writes_config_and_credential(tmp_path):
    cfg = tmp_path / "config.toml"
    creds = tmp_path / "credentials.toml"
    answers = io.StringIO("http://wcsubs.test\nadmin\ndev\napp-secret\n")
    code = run_wp_connect(stream=answers, out=lambda s: None,
                          config_path=cfg, credentials_path=creds,
                          connector_check=lambda c, p: "ok")
    assert code == 0
    site = load_wordpress_config(cfg)
    assert site.url == "http://wcsubs.test" and site.env == "dev"
    assert load_key("wordpress", path=creds) == "app-secret"


def test_wp_connect_refuses_production(tmp_path):
    cfg = tmp_path / "config.toml"
    creds = tmp_path / "credentials.toml"
    answers = io.StringIO("http://live.test\nadmin\nproduction\napp-secret\n")
    code = run_wp_connect(stream=answers, out=lambda s: None,
                          config_path=cfg, credentials_path=creds)
    assert code != 0
    assert load_wordpress_config(cfg) is None  # nothing written
    assert load_key("wordpress", path=creds) is None  # credential not written
