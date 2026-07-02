import asyncio

import httpx
import pytest

pytest.importorskip("mcp")  # the MCP SDK is an optional extra (heya-agent[mcp])

from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from heya.config import MCPServerConfig
from heya.mcp_oauth import (
    InMemoryTokenStorage,
    KeyringTokenStorage,
    LoopbackCallbackServer,
    make_token_storage,
    open_browser_redirect,
)


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


def test_open_browser_redirect_prints_and_opens(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("webbrowser.open", lambda u: calls.append(u) or True)
    asyncio.run(open_browser_redirect("https://auth.example/authorize?x=1"))
    assert calls == ["https://auth.example/authorize?x=1"]
    assert "authorize" in capsys.readouterr().out


def test_open_browser_redirect_survives_no_browser(monkeypatch):
    def boom(_u):
        raise RuntimeError("no browser")
    monkeypatch.setattr("webbrowser.open", boom)
    asyncio.run(open_browser_redirect("https://auth.example/x"))  # must not raise


def test_loopback_captures_code_and_state():
    async def scenario():
        cb = LoopbackCallbackServer()
        cb.start()
        try:
            waiter = asyncio.ensure_future(cb.wait_for_code())
            await asyncio.sleep(0)  # let the waiter create its future
            async with httpx.AsyncClient() as c:
                resp = await c.get(cb.redirect_uri, params={"code": "abc", "state": "xyz"})
            assert resp.status_code == 200
            code, state = await asyncio.wait_for(waiter, timeout=5)
            assert code == "abc" and state == "xyz"
        finally:
            cb.stop()
    asyncio.run(scenario())


def test_loopback_surfaces_error():
    async def scenario():
        cb = LoopbackCallbackServer()
        cb.start()
        try:
            waiter = asyncio.ensure_future(cb.wait_for_code())
            await asyncio.sleep(0)
            async with httpx.AsyncClient() as c:
                await c.get(cb.redirect_uri, params={"error": "access_denied"})
            with pytest.raises(RuntimeError):
                await asyncio.wait_for(waiter, timeout=5)
        finally:
            cb.stop()
    asyncio.run(scenario())


def test_loopback_stop_idempotent():
    cb = LoopbackCallbackServer()
    cb.start()
    cb.stop()
    cb.stop()  # must not raise


def test_loopback_binds_loopback_only():
    cb = LoopbackCallbackServer()
    cb.start()
    try:
        assert cb.redirect_uri.startswith("http://127.0.0.1:")
    finally:
        cb.stop()


def test_build_oauth_provider_uses_loopback_redirect():
    from heya.mcp_oauth import build_oauth_provider
    cb = LoopbackCallbackServer()
    try:
        server = MCPServerConfig(name="o", transport="http", url="https://o/mcp",
                                 auth="oauth", scopes=("a", "b"), oauth_client_name="Heya")
        provider = build_oauth_provider(server, storage=InMemoryTokenStorage(), loopback=cb)
        # the provider was constructed with our redirect_uri in its client metadata
        assert cb.redirect_uri in str(provider.context.client_metadata.redirect_uris)
    finally:
        cb.stop()
