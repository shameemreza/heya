import asyncio

import pytest

from heya.mcp_oauth import InMemoryTokenStorage, KeyringTokenStorage, make_token_storage
from heya.config import MCPServerConfig
from mcp.shared.auth import OAuthToken, OAuthClientInformationFull


def _token():
    return OAuthToken(access_token="at", token_type="Bearer", refresh_token="rt", expires_in=3600)


def _client_info():
    return OAuthClientInformationFull(client_id="cid", redirect_uris=["http://127.0.0.1:9/callback"])


class FakeKeyring:
    def __init__(self):
        self._store = {}

    def get_password(self, service, account):
        return self._store.get((service, account))

    def set_password(self, service, account, value):
        self._store[(service, account)] = value


def test_in_memory_round_trips():
    s = InMemoryTokenStorage()
    asyncio.run(s.set_tokens(_token()))
    assert asyncio.run(s.get_tokens()).access_token == "at"
    asyncio.run(s.set_client_info(_client_info()))
    assert asyncio.run(s.get_client_info()).client_id == "cid"


def test_in_memory_empty_returns_none():
    s = InMemoryTokenStorage()
    assert asyncio.run(s.get_tokens()) is None
    assert asyncio.run(s.get_client_info()) is None


def test_keyring_round_trips_via_fake_backend():
    kr = FakeKeyring()
    s = KeyringTokenStorage("srv", keyring_module=kr)
    asyncio.run(s.set_tokens(_token()))
    got = asyncio.run(s.get_tokens())
    assert got.access_token == "at" and got.refresh_token == "rt"
    asyncio.run(s.set_client_info(_client_info()))
    assert asyncio.run(s.get_client_info()).client_id == "cid"
    # stored under the heya-mcp service, server-scoped accounts
    assert kr.get_password("heya-mcp", "srv:tokens") is not None


def test_keyring_missing_backend_degrades(capsys):
    # keyring_module sentinel False => simulate "no working backend"
    s = KeyringTokenStorage("srv", keyring_module=False)
    asyncio.run(s.set_tokens(_token()))
    assert asyncio.run(s.get_tokens()).access_token == "at"  # in-memory fallback works
    assert "keychain" in capsys.readouterr().err.lower()


def test_make_token_storage_selects_by_config():
    mem = make_token_storage(MCPServerConfig(name="m", transport="http", url="https://m",
                                             auth="oauth", oauth_token_store="memory"))
    assert isinstance(mem, InMemoryTokenStorage)
    kc = make_token_storage(MCPServerConfig(name="k", transport="http", url="https://k",
                                            auth="oauth", oauth_token_store="keyring"))
    assert isinstance(kc, KeyringTokenStorage)
