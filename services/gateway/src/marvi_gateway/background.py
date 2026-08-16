"""A private event loop for async subsystems driven from sync tool handlers.

The tool registry is synchronous, and its handlers are called from inside
FastAPI's running loop. Async clients (MCP sessions, Playwright) therefore
cannot be driven directly: `asyncio.run` would refuse, and the sync Playwright
API refuses to start inside a running loop at all.

One background loop thread solves both. Handlers stay simple and synchronous;
long-lived async objects live on a loop that outlives any single request.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

DEFAULT_TIMEOUT = 60.0


class LoopThread:
    def __init__(self, name: str = "marvi-bg") -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True, name=name)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro, timeout: float = DEFAULT_TIMEOUT) -> Any:
        """Run a coroutine on the background loop and wait for its result."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=5)
