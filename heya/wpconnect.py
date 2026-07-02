"""The `heya wp connect` setup flow: capture a dev or staging WordPress site's
url, user, environment, and application password, store them, and confirm."""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

from .config import WPSiteConfig, default_config_path, write_wordpress_config
from .credentials import default_credentials_path, save_key
from .wpsite import build_wp_connector


def run_wp_connect(*, stream=None, out=print, config_path=None,
                   credentials_path=None, connector_check=None) -> int:
    stream = stream if stream is not None else sys.stdin
    config_path = Path(config_path) if config_path else None
    credentials_path = Path(credentials_path) if credentials_path else None

    def ask(prompt: str) -> str:
        out(prompt)
        line = stream.readline()
        if line == "":
            raise EOFError
        return line.strip()

    def ask_secret(prompt: str) -> str:
        out(prompt)
        if stream is sys.stdin and sys.stdin.isatty():
            return getpass.getpass("").strip()
        line = stream.readline()
        if line == "":
            raise EOFError
        return line.strip()

    out("Connect Heya to a WordPress or WooCommerce site (dev or staging only).")
    url = ask("Site URL (for example http://wcsubs.test):")
    user = ask("WordPress username:")
    env = ask("Environment, dev or staging (production is not allowed):").lower()
    if env not in ("dev", "staging"):
        out("Refusing: only dev or staging sites can be connected.")
        return 1
    password = ask_secret("Application password:")
    if not url or not user or not password:
        out("Refusing: url, user, and application password are all required.")
        return 1

    config = WPSiteConfig(url=url, user=user, env=env)
    cfg_path = config_path or default_config_path()
    creds_path = credentials_path or default_credentials_path()
    write_wordpress_config(cfg_path, config)
    save_key(config.password_key, password, path=creds_path)

    check = connector_check
    if check is None:
        def check(c, p):
            wp = build_wp_connector(c, p)
            return wp.list_abilities() if wp is not None else "Error: could not connect."
    result = check(config, password)
    out(f"Connected {url}.")
    out(result if result.startswith("Error") else "It responded. The site tools are now available.")
    return 0
