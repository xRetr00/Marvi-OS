"""Voice gets the tools chat has.

Voice had seven, written by hand; chat had seventeen, from the Gateway's
registry. Nobody kept them in step, so asking Marvi out loud to search the web
got "I don't have a web search tool" -- true, and the same question typed
worked. Every tool added since, and every MCP server, reached one surface only.
"""

from __future__ import annotations

import contextlib

import httpx

from marvi_agent import tools as tools_module
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


async def test_voice_preserves_gateway_object_arguments_for_account_tools() -> None:
    payload = {
        "tools": [
            {
                "name": "account_tool_execute",
                "description": "Execute a discovered account tool",
                "arguments": ["arguments", "tool"],
                "optional": [],
                "sensitive": False,
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string"},
                        "arguments": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["tool", "arguments"],
                },
            }
        ]
    }

    built = await GatewayTools(client=gateway(payload=payload)).from_gateway()

    assert built[0].info.raw_schema["parameters"]["properties"]["arguments"]["type"] == "object"


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


async def test_spoken_recall_uses_the_canonical_gateway_memory_tool() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "status": "executed",
                "result": {"results": [{"subject": "Sam", "body": "likes tea"}]},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tools = GatewayTools(client=client)

    answer = await tools.recall(None, "Sam")
    await client.aclose()

    assert answer == "Sam: likes tea"
    assert seen[-1].url.path == "/tools/memory_recall"


# -- deferred loading --------------------------------------------------------


async def test_only_the_core_tools_load_up_front() -> None:
    """Fifty-six tools, five thousand tokens of schema, in front of the model on
    every turn including the ones that are somebody saying good morning. Past
    thirty to fifty, tool selection degrades."""
    import httpx

    from marvi_agent.tools import GatewayTools

    catalogue = {
        "tools": [
            {"name": "room_state", "description": "Room", "arguments": [], "core": True},
            {"name": "tool_search", "description": "Find a tool", "arguments": ["query"], "core": True},
            {"name": "send_email", "description": "Send mail", "arguments": ["to"]},
            {"name": "browser_open", "description": "Open a page", "arguments": ["url"]},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=catalogue)

    tools = GatewayTools(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    loaded = await tools.from_gateway(everything=False)

    # `room_state` is in SPOKEN_BADLY -- voice writes that one by hand -- so
    # what is left of the core here is the search itself.
    assert [tool.info.name for tool in loaded] == ["tool_search"]


async def test_a_search_makes_the_tools_it_found_callable() -> None:
    """The half that matters. Telling the model a tool exists and leaving it
    uncallable produces a confident description of something that then fails."""
    import httpx

    from marvi_agent.tools import GatewayTools

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/tools":
            return httpx.Response(
                200,
                json={
                    "tools": [
                        {
                            "name": "tool_search",
                            "description": "Find a tool",
                            "arguments": ["query"],
                            "core": True,
                        },
                        {"name": "send_email", "description": "Send mail", "arguments": ["to"]},
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "executed",
                "result": {"tools": [{"name": "send_email", "description": "Send mail"}]},
            },
        )

    class Agent:
        def __init__(self) -> None:
            self.tools: list = []

        async def update_tools(self, tools) -> None:
            self.tools = list(tools)

    tools = GatewayTools(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    agent = Agent()

    await tools.from_gateway(everything=False)
    tools.attach(agent)
    await tools._call("tool_search", {"query": "email"})

    assert [tool.info.name for tool in agent.tools] == ["send_email"]


async def test_searching_twice_does_not_add_the_same_tool_twice() -> None:
    import httpx

    from marvi_agent.tools import GatewayTools

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/tools":
            return httpx.Response(
                200,
                json={
                    "tools": [
                        {"name": "tool_search", "description": "Find", "arguments": ["query"], "core": True},
                        {"name": "send_email", "description": "Send mail", "arguments": ["to"]},
                    ]
                },
            )
        return httpx.Response(
            200,
            json={"status": "executed", "result": {"tools": [{"name": "send_email"}]}},
        )

    class Agent:
        def __init__(self) -> None:
            self.tools: list = []

        async def update_tools(self, tools) -> None:
            self.tools = list(tools)

    tools = GatewayTools(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    agent = Agent()

    await tools.from_gateway(everything=False)
    tools.attach(agent)
    await tools._call("tool_search", {"query": "email"})
    await tools._call("tool_search", {"query": "email"})

    assert [tool.info.name for tool in agent.tools] == ["send_email"]


async def test_a_slow_tool_call_is_covered_by_a_spoken_filler() -> None:
    """The other half of the no-narration rule.

    The persona forbids announcing a tool call, because the announcement was
    truncated the moment the call began -- "Let me check what I know about
    this", then silence. That fixed the truncation and left the gap. LiveKit's
    own latency guidance names the missing half: a thinking sound, played by
    the framework so a tool call cannot cut it off.
    """
    opened: list = []

    class FakeContext:
        @contextlib.asynccontextmanager
        async def with_filler(self, source, *, delay=0, interval=None, max_steps=None):
            opened.append({"source": source, "delay": delay, "max_steps": max_steps})
            yield

    tools = GatewayTools(client=gateway(seen=[]))
    built = await tools.from_gateway(everything=False)

    await built[0](raw_arguments={"query": "who won"}, context=FakeContext())

    assert opened == [{"source": tools_module.THINKING, "delay": tools_module.FILLER_DELAY,
                       "max_steps": 1}]
    # Only after the session has been idle that long, so a fast call is silent.
    assert tools_module.FILLER_DELAY > 0.5


async def test_a_tool_called_without_a_context_still_runs() -> None:
    """Injection is conditional. A required context would fail the bind
    instead of running the tool."""
    seen: list = []
    tools = GatewayTools(client=gateway(seen=seen))
    built = await tools.from_gateway(everything=False)

    await built[0](raw_arguments={"query": "who won"})

    assert [str(r.url.path) for r in seen][-1] == "/tools/web_search"


async def test_the_whole_catalogue_loads_unless_deferring_is_asked_for() -> None:
    """Deferring is off by default, and three sweeps of the same 123 turns are
    why. Held back, Marvi refused twenty-three things she can do. Given the
    names but not the schemas she called them directly and LiveKit answered
    `unknown AI function` ten times, while `tool_search` -- the step that was
    supposed to bridge that -- fired once in 123 turns."""
    import httpx

    from marvi_agent.tools import GatewayTools

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "tools": [
                    {"name": "tool_search", "description": "Find", "arguments": ["query"],
                     "core": True},
                    {"name": "send_email", "description": "Send mail", "arguments": ["to"]},
                    {"name": "browser_open", "description": "Open", "arguments": ["url"]},
                ]
            },
        )

    tools = GatewayTools(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    loaded = {tool.info.name for tool in await tools.from_gateway()}

    assert {"send_email", "browser_open", "tool_search"} <= loaded


async def test_deferring_can_be_turned_back_on(monkeypatch) -> None:
    import httpx

    from marvi_agent.tools import DEFER_SETTING, GatewayTools

    monkeypatch.setenv(DEFER_SETTING, "on")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "tools": [
                    {"name": "tool_search", "description": "Find", "arguments": ["query"],
                     "core": True},
                    {"name": "send_email", "description": "Send mail", "arguments": ["to"]},
                ]
            },
        )

    tools = GatewayTools(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    loaded = {tool.info.name for tool in await tools.from_gateway()}

    assert loaded == {"tool_search"}


async def test_the_bridge_calls_a_tool_that_is_not_loaded() -> None:
    r"""Taken from Hermes Agent, which pairs `tool_search` with a `tool_call`
    bridge instead of making the model do a two-step. The model already emits
    it: LiveKit logged `unknown AI function \`tool_call\`` twice in one sweep,
    reaching for a bridge by the name the convention gave it, into nothing."""
    import httpx

    from marvi_agent.tools import GatewayTools

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/tools":
            return httpx.Response(
                200,
                json={
                    "tools": [
                        {"name": "tool_search", "description": "Find", "arguments": ["query"],
                         "core": True},
                        {"name": "browser_close", "description": "Close", "arguments": []},
                    ]
                },
            )
        seen.append(request.url.path)
        return httpx.Response(200, json={"status": "executed", "result": {"closed": True}})

    tools = GatewayTools(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await tools.from_gateway(everything=False)

    answer = await tools.tool_call(None, "browser_close", {})

    assert seen == ["/tools/browser_close"]
    assert "closed" in answer


async def test_the_bridge_names_the_near_miss_instead_of_failing() -> None:
    """A tool that does not exist is a recoverable turn, not a dead one. The
    model gets the nearest real name and the way to search."""
    import httpx

    from marvi_agent.tools import GatewayTools

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "tools": [
                    {"name": "tool_search", "description": "Find", "arguments": ["query"],
                     "core": True},
                    {"name": "browser_close", "description": "Close", "arguments": []},
                ]
            },
        )

    tools = GatewayTools(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await tools.from_gateway()

    answer = await tools.tool_call(None, "browser", {})

    assert "browser_close" in answer
    assert "tool_search" in answer
