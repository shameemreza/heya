"""Outbound host safety: block only cloud-metadata / link-local addresses.

Support engineers hit local dev sites (localhost, 127.0.0.1, LAN) and live
customer sites constantly, so loopback, private, and public addresses are all
allowed. Only link-local (169.254.0.0/16 and fe80::/10) is blocked, which is
where cloud instance-metadata (169.254.169.254) lives.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx


class BlockedHostError(Exception):
    pass


def is_blocked_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_link_local


def check_host(host: str, *, resolver=socket.getaddrinfo) -> None:
    if not host:
        raise BlockedHostError("no host in URL")
    try:
        infos = resolver(host, None)
    except socket.gaierror as exc:
        raise BlockedHostError(f"cannot resolve host {host!r}: {exc}") from exc
    for info in infos:
        ip = info[4][0]
        if is_blocked_ip(ip):
            raise BlockedHostError(
                f"refusing to reach {host} ({ip}): link-local/metadata address")


def guarded_get(client: httpx.Client, url: str, *, max_redirects: int = 5,
                resolver=socket.getaddrinfo) -> httpx.Response:
    current = url
    for _ in range(max_redirects + 1):
        host = urlparse(current).hostname or ""
        check_host(host, resolver=resolver)
        resp = client.get(current, follow_redirects=False)
        if resp.is_redirect and "location" in resp.headers:
            current = urljoin(current, resp.headers["location"])
            continue
        return resp
    raise BlockedHostError(f"too many redirects from {url}")
