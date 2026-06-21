"""Heya's host-side pieces for MCP OAuth 2.1.

The official mcp SDK's OAuthClientProvider owns the protocol (discovery, dynamic
client registration, PKCE, token exchange, refresh). Heya supplies only what a
host must: open the user's browser at the authorization URL, catch the loopback
redirect, and store tokens. All SDK type names stay in this module and the
runtime opener; the rest of Heya is OAuth-agnostic.
"""
from __future__ import annotations

import sys

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
