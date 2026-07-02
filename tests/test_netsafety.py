# tests/test_netsafety.py
import socket

import httpx
import pytest

from heya.netsafety import BlockedHostError, check_host, guarded_get, is_blocked_ip


def _resolver_for(ip):
    def r(host, *a, **k):
        return [(socket.AF_INET, None, None, "", (ip, 0))]
    return r

def test_link_local_metadata_blocked():
    assert is_blocked_ip("169.254.169.254") is True
    with pytest.raises(BlockedHostError):
        check_host("metadata", resolver=_resolver_for("169.254.169.254"))

def test_loopback_allowed():
    assert is_blocked_ip("127.0.0.1") is False
    check_host("localhost", resolver=_resolver_for("127.0.0.1"))  # no raise

def test_private_allowed():
    assert is_blocked_ip("192.168.1.10") is False
    check_host("wp.test", resolver=_resolver_for("192.168.1.10"))  # no raise

def test_public_allowed():
    assert is_blocked_ip("93.184.216.34") is False
    check_host("example.com", resolver=_resolver_for("93.184.216.34"))  # no raise

def test_guarded_get_blocks_redirect_into_metadata():
    def handler(request):
        if request.url.host == "start":
            return httpx.Response(302, headers={"Location": "http://meta/"})
        return httpx.Response(200, text="secret")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    def resolver(host, *a, **k):
        ip = "169.254.169.254" if host == "meta" else "93.184.216.34"
        return [(socket.AF_INET, None, None, "", (ip, 0))]
    with pytest.raises(BlockedHostError):
        guarded_get(client, "http://start/", resolver=resolver)
