"""Voice gets the tools chat has.

Voice had seven, written by hand; chat had seventeen, from the Gateway's
registry. Nobody kept them in step, so asking Marvi out loud to search the web
got "I don't have a web search tool" -- true, and the same question typed
worked. Every tool added since, and every MCP server, reached one surface only.
"""

from __future__ import annotations

import httpx

from marvi_agent.tools import GatewayTools

CATALOGUE = {
    "tools": [
        {
            "name": "web_search",
            "description": "Search the web",
            "arguments": ["query"],
            "optional": ["limit"],
            "sensitive": False,
        },
        {
            "name": "room_set_light",
            "description": "Change the room light",
            "arguments": ["on"],
            "optional": [],
            "sensitive": True,
        },
    ]
}


def gateway(payload=CATALOGUE, seen: list | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path == "/tools":
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json={"status": "executed", "result": "ok"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_the_gateway_tools_reach_the_voice_agent() -> None:
    built = await GatewayTools(client=gateway()).from_gateway()

    assert [tool.info.name for tool in built] == ["web_search"]


async def test_a_tool_written_better_by_hand_is_not_duplicated() -> None:
    """`room_set_light` is spoken as "turn the light on"; the typed schema is
    worse at that, and offering both makes the model choose between them."""
    built = await GatewayTools(client=gateway()).from_gateway()

    assert "room_set_light" not in [tool.info.name for tool in built]


async def test_the_schema_carries_what_is_required() -> None:
    built = await GatewayTools(client=gateway()).from_gateway()
    schema = built[0].info.raw_schema

    assert schema["parameters"]["required"] == ["query"]
    assert set(schema["parameters"]["properties"]) == {"query", "limit"}


async def test_calling_one_goes_through_the_gateway(monkeypatch) -> None:
    """Not around it. `/tools/{name}` is the one path with the confirmation
    flow and the audit line on it."""
    seen: list = []
    tools = GatewayTools(client=gateway(seen=seen))
    built = await tools.from_gateway()

    await built[0](raw_arguments={"query": "who won"})

    assert [str(r.url.path) for r in seen][-1] == "/tools/web_search"


async def test_a_gateway_that_cannot_be_reached_is_not_fatal() -> None:
    """Voice with seven tools beats no voice at all."""

    def broken(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nothing listening")

    tools = GatewayTools(client=httpx.AsyncClient(transport=httpx.MockTransport(broken)))

    assert await tools.from_gateway() == []
