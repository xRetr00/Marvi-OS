"""Exercise proxy authentication and the DNS-to-connection admission boundary."""

import asyncio
import socket

import httpx
import pytest
from pproxy.server import ProxyDirect

from marvi_gateway.browser_network import BrowserNetwork, PublicNetwork


@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["93.184.215.14", "10.0.0.1"], ["::1"]])
def test_private_dns_answers_never_reach_connector(monkeypatch, addresses):
    monkeypatch.delenv("MARVI_BROWSER_TEST_ORIGINS", raising=False)
    connected = []

    async def exercise():
        async def resolve(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in addresses]

        async def connect(self, host, *args):
            connected.append(host)

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
        monkeypatch.setattr(ProxyDirect, "wait_open_connection", connect)
        with pytest.raises(ValueError, match="destination refused"):
            await PublicNetwork().wait_open_connection("fixture.example", 443, None, 0)

    asyncio.run(exercise())
    assert connected == []


def test_verified_numeric_ip_is_passed_to_upstream_connector(monkeypatch):
    monkeypatch.delenv("MARVI_BROWSER_TEST_ORIGINS", raising=False)
    connected = []

    async def exercise():
        async def resolve(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]

        async def connect(self, host, *args):
            connected.append(host)
            return "connected"

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
        monkeypatch.setattr(ProxyDirect, "wait_open_connection", connect)
        assert await PublicNetwork().wait_open_connection("fixture.example", 443, None, 0) == "connected"

    asyncio.run(exercise())
    assert connected == ["93.184.215.14"]


def test_real_proxy_rejects_missing_credentials_and_exits():
    network = BrowserNetwork()
    try:
        with httpx.Client(proxy=network.settings["server"], timeout=5, trust_env=False) as client:
            response = client.get("http://example.com/")
        assert response.status_code == 407
    finally:
        network.close()
    assert network.process.poll() == 0
