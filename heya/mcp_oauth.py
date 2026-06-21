"""Heya's host-side pieces for MCP OAuth 2.1.

The official mcp SDK's OAuthClientProvider owns the protocol (discovery, dynamic
client registration, PKCE, token exchange, refresh). Heya supplies only what a
host must: open the user's browser at the authorization URL, catch the loopback
redirect, and store tokens. All SDK type names stay in this module and the
runtime opener; the rest of Heya is OAuth-agnostic.
"""
from __future__ import annotations

import asyncio
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

from mcp.shared.auth import OAuthToken, OAuthClientInformationFull


def _import_keyring():
    """Import seam so tests can simulate keyring presence/absence."""
    import keyring
    return keyring


class InMemoryTokenStorage:
    """TokenStorage held in memory for the process lifetime (nothing at rest)."""

    def __init__(self) -> None:
        self._tokens: OAuthToken | None = None
        self._client: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self._tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self._client

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client = client_info


class KeyringTokenStorage:
    """TokenStorage backed by the OS keychain; degrades to memory if unavailable."""

    _SERVICE = "heya-mcp"

    def __init__(self, server_name: str, *, keyring_module=None) -> None:
        self._name = server_name
        if keyring_module is None:
            try:
                keyring_module = _import_keyring()
            except Exception:
                keyring_module = False
        self._kr = keyring_module
        self._mem = InMemoryTokenStorage()
        if not self._kr:
            print(
                f"MCP OAuth: no OS keychain backend available; tokens for {server_name!r} "
                "will not persist beyond this session.",
                file=sys.stderr,
            )

    async def get_tokens(self) -> OAuthToken | None:
        if not self._kr:
            return await self._mem.get_tokens()
        raw = self._kr.get_password(self._SERVICE, f"{self._name}:tokens")
        return OAuthToken.model_validate_json(raw) if raw else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        if not self._kr:
            return await self._mem.set_tokens(tokens)
        self._kr.set_password(self._SERVICE, f"{self._name}:tokens", tokens.model_dump_json())

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        if not self._kr:
            return await self._mem.get_client_info()
        raw = self._kr.get_password(self._SERVICE, f"{self._name}:client")
        return OAuthClientInformationFull.model_validate_json(raw) if raw else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        if not self._kr:
            return await self._mem.set_client_info(client_info)
        self._kr.set_password(self._SERVICE, f"{self._name}:client", client_info.model_dump_json())


def make_token_storage(server):
    """Pick the storage backend for a server per its oauth_token_store config."""
    if server.oauth_token_store == "keyring":
        return KeyringTokenStorage(server.name)
    return InMemoryTokenStorage()


async def open_browser_redirect(url: str) -> None:
    """Print the authorization URL, then best-effort open the browser."""
    print(f"Opening browser to authorize: {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass  # headless / no browser: the printed URL is the fallback


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (stdlib name)
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = parse_qs(parsed.query)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body>Authorization complete. You can close this tab.</body></html>")
        self.server.loopback._resolve(params)  # type: ignore[attr-defined]

    def log_message(self, *args):  # silence the default stderr access log
        pass


class LoopbackCallbackServer:
    """One-shot loopback HTTP server that captures the OAuth redirect."""

    def __init__(self) -> None:
        self._server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
        self._server.loopback = self  # type: ignore[attr-defined]
        self.port = self._server.server_address[1]
        self.redirect_uri = f"http://127.0.0.1:{self.port}/callback"
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._future: asyncio.Future | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    async def wait_for_code(self) -> tuple[str, str | None]:
        self._loop = asyncio.get_running_loop()
        self._future = self._loop.create_future()
        return await self._future

    def _resolve(self, params: dict) -> None:
        # Runs on the server thread; hand the result to the asyncio waiter.
        if self._loop is None or self._future is None or self._future.done():
            return
        if "error" in params:
            self._loop.call_soon_threadsafe(
                self._future.set_exception, RuntimeError(params["error"][0])
            )
            return
        code = params.get("code", [""])[0]
        state = params.get("state", [None])[0]
        self._loop.call_soon_threadsafe(self._future.set_result, (code, state))

    def stop(self) -> None:
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
