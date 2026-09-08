"""Loopback-only browser egress using unchanged pproxy, without TLS interception.

The plugin returns the validated IP to upstream's connector. Redirects and new
hosts therefore pass DNS admission even when Chromium skips Playwright routes.
Only the test constructor supplies private fixture origins. No traffic is logged.
"""
from __future__ import annotations

import ipaddress
import asyncio
import json
import os
import queue
import socket
import subprocess
import sys
import threading
from urllib.parse import urlsplit
from uuid import uuid4

from pproxy.server import ProxyDirect


class PublicNetwork(ProxyDirect):
    async def wait_open_connection(self, host, port, local_addr, family):
        allowed = {tuple(item) for item in json.loads(os.environ.get("MARVI_BROWSER_TEST_ORIGINS", "[]"))}
        try:
            addresses = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
            if (host, port) not in allowed and any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
                raise ValueError("Non-public address")
            return await super().wait_open_connection(addresses[0][4][0], port, local_addr, family)
        except (OSError, ValueError, IndexError) as exc:
            raise ValueError("Browser destination refused") from exc


class BrowserNetwork:
    def __init__(self, allowed_origins=()):
        token = uuid4().hex
        origins = []
        for origin in allowed_origins:
            parsed = urlsplit(origin)
            origins.append((parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)))
        self.process = subprocess.Popen(
            [sys.executable, "-m", "marvi_gateway.browser_network"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            env={**os.environ, "MARVI_BROWSER_PROXY_TOKEN": token, "MARVI_BROWSER_TEST_ORIGINS": json.dumps(origins)},
        )
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(self.process.stdout.readline()), daemon=True).start()
        try:
            port = json.loads(ready.get(timeout=15))["port"]
            self.settings = {"server": f"http://127.0.0.1:{port}", "username": "marvi", "password": token}
        except Exception:
            self.close()
            raise RuntimeError("Browser network service did not start") from None

    def close(self):
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
        if self.process.stdout:
            self.process.stdout.close()


async def main():
    import pproxy
    listener = pproxy.Server("http://127.0.0.1:0#marvi:" + os.environ["MARVI_BROWSER_PROXY_TOKEN"])
    listener.port = 0
    server = await listener.start_server({"rserver": [PublicNetwork()], "authtime": 0})
    try:
        print(json.dumps({"port": server.sockets[0].getsockname()[1]}), flush=True)
        await asyncio.to_thread(sys.stdin.read)
    finally:
        server.close()
        await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
