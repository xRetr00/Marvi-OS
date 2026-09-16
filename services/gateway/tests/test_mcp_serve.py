"""Another agent asks Marvi what she remembers, over the real MCP protocol."""

from __future__ import annotations

import json

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import Implementation

from marvi_gateway import mcp_serve


def _gateway(seen: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"path": request.url.path, "body": json.loads(request.content)})
        if request.url.path.endswith("/memory_recall"):
            return httpx.Response(200, json={"status": "executed", "tool": "memory_recall",
                                             "result": {"memories": ["prefers tea"]}})
        if request.url.path.endswith("/memory_remember_external"):
            return httpx.Response(200, json={"status": "executed", "tool": "memory_remember_external",
                                             "result": {"id": 7, "source": "mcp:test-client",
                                                        "trusted": False}})
        return httpx.Response(200, json={"status": "failed", "tool": "chat_search", "error": "boom"})

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_a_host_lists_and_calls_the_read_only_tools() -> None:
    seen: list[dict] = []
    server = mcp_serve.build(http=_gateway(seen))
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        listed = {tool.name for tool in (await client.list_tools()).tools}
        # The MCP names, not the Gateway ones: the write is offered as
        # `memory_remember` and lands on the internal external-write tool.
        assert listed == {'memory_recall', 'memory_remember', 'chat_search'}

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


@pytest.mark.asyncio
async def test_a_memory_written_from_outside_carries_who_wrote_it() -> None:
    """M4: a fact from a coding agent is marked untrusted and sourced to it."""
    seen: list[dict] = []
    server = mcp_serve.build(http=_gateway(seen))
    async with create_connected_server_and_client_session(
        server._mcp_server, client_info=Implementation(name="test-client", version="1")
    ) as client:
        answer = await client.call_tool("memory_remember", {"subject": "Tea", "body": "Prefers tea."})

    assert "mcp:test-client" in answer.content[0].text
    wrote = next(one for one in seen if one["path"].endswith("memory_remember_external"))
    assert wrote["body"]["arguments"]["source"] == "mcp:test-client"
    # The Gateway tool it calls is internal: no model is ever offered it.
    from pathlib import Path
    from tempfile import mkdtemp

    from marvi_gateway.memory import MemoryStore, register_memory_tools
    from marvi_gateway.tools import ToolRegistry

    registry = ToolRegistry()
    register_memory_tools(registry, MemoryStore(Path(mkdtemp()) / "m.db"))
    assert registry.get("memory_remember_external").internal is True
    assert "memory_remember_external" not in {spec.name for spec in registry}


def test_an_unnamed_client_still_gets_a_source() -> None:
    assert mcp_serve.client_name(object()) == mcp_serve.UNKNOWN_CLIENT


def test_forgetting_is_still_not_offered() -> None:
    assert mcp_serve.call_gateway("memory_forget", {"id": 1}) == "memory_forget is not offered over MCP"
