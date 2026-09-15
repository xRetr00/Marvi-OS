"""Another agent asks Marvi what she remembers, over the real MCP protocol."""

from __future__ import annotations

import json

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from marvi_gateway import mcp_serve


def _gateway(seen: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"path": request.url.path, "body": json.loads(request.content)})
        if request.url.path.endswith("/memory_recall"):
            return httpx.Response(200, json={"status": "executed", "tool": "memory_recall",
                                             "result": {"memories": ["prefers tea"]}})
        return httpx.Response(200, json={"status": "failed", "tool": "chat_search", "error": "boom"})

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_a_host_lists_and_calls_the_read_only_tools() -> None:
    seen: list[dict] = []
    server = mcp_serve.build(http=_gateway(seen))
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        listed = {tool.name for tool in (await client.list_tools()).tools}
        assert listed == set(mcp_serve.EXPOSED)

        recalled = await client.call_tool("memory_recall", {"query": "drinks"})
        assert "prefers tea" in recalled.content[0].text
        failed = await client.call_tool("chat_search", {"query": "x"})
        assert "did not run" in failed.content[0].text

    assert seen[0] == {"path": "/tools/memory_recall", "body": {"arguments": {"query": "drinks"}}}


def test_a_missing_gateway_is_said_plainly(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_GATEWAY_URL", "http://127.0.0.1:9")

    def refuse(request):
        raise httpx.ConnectError("refused")

    answer = mcp_serve.call_gateway(
        "memory_recall", {"query": "x"}, http=httpx.Client(transport=httpx.MockTransport(refuse))
    )
    assert "Is Marvi running?" in answer


def test_writes_are_not_offered() -> None:
    assert mcp_serve.call_gateway("memory_forget", {"id": 1}) == "memory_forget is not offered over MCP"
