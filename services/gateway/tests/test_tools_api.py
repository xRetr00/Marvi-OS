"""Calling a tool over HTTP.

The router's rules — validation, confirmation, dedup — are tested beside the
router. What is here is the property that only shows up under load: a tool
handler is ordinary blocking code, and the Gateway has to keep answering while
one runs.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_a_slow_tool_does_not_stop_the_gateway_answering(tmp_path) -> None:
    """Handlers are ordinary blocking functions and were called straight from
    the async route, so the event loop sat inside them.

    `/health` and `/runtime` stopped answering, the shell declared "Gateway
    unavailable" over a Gateway that was alive and merely busy, and asking
    Marvi to browse the skills store — nine HTTP round trips — looked exactly
    like a crash.
    """
    import asyncio
    import time

    from httpx import ASGITransport, AsyncClient

    from marvi_gateway.app import create_app
    from marvi_gateway.runtime import RuntimeStore
    from marvi_gateway.tools import ToolRegistry, ToolSpec

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="slow_read",
            description="a tool that takes its time",
            arguments={},
            sensitive=False,
            handler=lambda: time.sleep(0.6) or {"ok": True},
        )
    )
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    app = create_app(version="0.1.0-test", runtime=runtime, tools=registry)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://marvi.local"
    ) as http:
        # Timed from before the slow call starts, not after. Measuring inside
        # meant the clock started once the block had already finished, and the
        # test passed with the fix reverted -- which is the only reason it was
        # checked.
        began = time.monotonic()
        slow = asyncio.create_task(http.post("/tools/slow_read", json={"arguments": {}}))
        await asyncio.sleep(0)  # let it start, and block if it is going to
        # This is the request the shell polls every two seconds, and the one
        # that must not wait for a web search to finish.
        health = await http.get("/health")
        waited = time.monotonic() - began
        answer = await slow

    assert health.status_code == 200
    assert waited < 0.4, f"/health waited {waited:.2f}s behind a slow tool"
    assert answer.json()["status"] == "executed"
