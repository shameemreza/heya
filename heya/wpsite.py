"""Talk to a WordPress site's Abilities API and the WooCommerce REST API.

Best-effort throughout: every method returns a readable string, and on any
error returns an `Error: ...` string rather than raising. Dev and staging sites
only; the production guard lives in build_wp_connector."""
from __future__ import annotations

import json

import httpx

from .config import WPSiteConfig

_ABILITIES = "wp/v2/abilities"


def encode_ability_name(name: str) -> str:
    """JSON-pointer encode an ability name for the REST path (~ then /)."""
    return name.replace("~", "~0").replace("/", "~1")


def _format(value) -> str:
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)[:6000]
    except Exception:
        return str(value)[:6000]


def _error(resp) -> str:
    body = None
    try:
        body = resp.json()
    except Exception:
        body = None
    status = getattr(resp, "status_code", 500)
    if isinstance(body, dict) and (body.get("code") or body.get("message")):
        return f"Error: {status} {body.get('code', '')} {body.get('message', '')}".strip()
    snippet = (getattr(resp, "text", "") or "")[:500]
    return f"Error: {status} from the site. {snippet}".strip()


class WPClient:
    # Dev/staging environment guard is enforced in build_wp_connector, the intended constructor.
    def __init__(self, base_url, user, password, *, client=None, timeout=20.0):
        self.base = base_url.rstrip("/") + "/wp-json"
        if client is not None:
            self._client = client
        else:
            # No follow_redirects: prevents Basic-auth credentials from being resent to a cross-host redirect target.
            self._client = httpx.Client(auth=httpx.BasicAuth(user, password), timeout=timeout)

    def list_abilities(self, *, per_page=50) -> str:
        try:
            resp = self._client.get(f"{self.base}/{_ABILITIES}", params={"per_page": per_page})
        except Exception as exc:
            return f"Error: could not reach the site: {exc}"
        if getattr(resp, "status_code", 500) >= 400:
            return _error(resp)
        try:
            data = resp.json()
        except Exception:
            return "Error: the site did not return JSON for the abilities list."
        items = data.get("abilities", []) if isinstance(data, dict) else data
        if not items:
            return "No abilities are registered on this site."
        lines = ["Abilities on this site (run one with wp_run_ability):"]
        try:
            for a in items:
                name = a.get("name", "?")
                label = a.get("label", "")
                desc = a.get("description", "")
                lines.append(f"- {name}: {label}. {desc}".rstrip())
        except Exception:
            return "Error: could not read the abilities list."
        return "\n".join(lines)

    def get_ability(self, name) -> str:
        try:
            resp = self._client.get(f"{self.base}/{_ABILITIES}/{encode_ability_name(name)}")
        except Exception as exc:
            return f"Error: could not reach the site: {exc}"
        if getattr(resp, "status_code", 500) >= 400:
            return _error(resp)
        try:
            return _format(resp.json())
        except Exception:
            return "Error: the site did not return JSON for the ability."

    def run_ability(self, name, ability_input) -> str:
        url = f"{self.base}/{_ABILITIES}/{encode_ability_name(name)}/run"
        try:
            resp = self._client.post(url, json={"input": ability_input or {}})
        except Exception as exc:
            return f"Error: could not reach the site: {exc}"
        if getattr(resp, "status_code", 500) >= 400:
            return _error(resp)
        try:
            return _format(resp.json())
        except Exception:
            return getattr(resp, "text", "") or "(no output)"

    def rest(self, method, path, body=None) -> str:
        method = (method or "GET").upper()
        if method not in ("GET", "POST", "PUT", "DELETE"):
            return f"Error: unsupported method {method!r}."
        p = path if path.startswith("/") else "/" + path
        url = f"{self.base}{p}"
        try:
            resp = self._client.request(method, url, json=body if body is not None else None)
        except Exception as exc:
            return f"Error: could not reach the site: {exc}"
        if getattr(resp, "status_code", 500) >= 400:
            return _error(resp)
        try:
            return _format(resp.json())
        except Exception:
            return getattr(resp, "text", "") or "(no output)"


def build_wp_connector(config: WPSiteConfig, password, *, client=None) -> "WPClient | None":
    """Build a WPClient, or None if the site is not dev/staging or has no password."""
    if config is None or not config.is_allowed_env() or not password:
        return None
    return WPClient(config.url, config.user, password, client=client)
