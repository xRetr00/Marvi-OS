"""MCP bridge tests.

A fake session stands in for a real MCP server so schema mapping, policy, and
failure handling can be exercised without spawning subprocesses.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.app import create_app
from marvi_gateway.mcp_bridge import (
    McpBridge,
    McpUnavailableError,
    load_server_config,
    register_mcp_tools,
    schema_arguments,
)
from marvi_gateway.runtime import RuntimeStore
from marvi_gateway.tools import InvalidArgumentsError, ToolRegistry


def tool(name, description="", read_only=False, schema=None):
    return SimpleNamespace(
        name=name,
        description=description,
        annotations=SimpleNamespace(readOnlyHint=read_only),
        inputSchema=schema,
    )


class FakeSession:
    def __init__(self, tools, fail=False):
        self._tools = tools
        self._fail = fail
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self):
        if self._fail:
            raise RuntimeError("server died")
        return SimpleNamespace(tools=self._tools)

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return SimpleNamespace(
            content=[SimpleNamespace(text=f"ran {name}")], isError=False
        )


def bridge_with(tools, name="docs", fail=False):
    session = FakeSession(tools, fail=fail)

    async def factory(spec):
        return session

    bridge = McpBridge(servers=[{"name": name}], session_factory=factory)
    return bridge, session


# -- config -----------------------------------------------------------------


def test_inline_config_is_read_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_MCP_SERVERS", json.dumps({"servers": [{"name": "a", "command": "x"}]}))
    assert load_server_config() == [{"name": "a", "command": "x"}]


def test_a_config_file_is_read_when_no_inline_config(monkeypatch, tmp_path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"servers": [{"name": "b", "command": "y"}]}), encoding="utf-8")
    monkeypatch.delenv("MARVI_MCP_SERVERS", raising=False)
    monkeypatch.setenv("MARVI_MCP_CONFIG", str(path))
    assert load_server_config()[0]["name"] == "b"


def test_absent_or_broken_config_means_no_servers(monkeypatch) -> None:
    monkeypatch.delenv("MARVI_MCP_CONFIG", raising=False)
    monkeypatch.setenv("MARVI_MCP_SERVERS", "{not json")
    assert load_server_config() == []
    monkeypatch.setenv("MARVI_MCP_SERVERS", "")
    assert load_server_config() == []


def test_servers_without_a_name_are_ignored(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_MCP_SERVERS", json.dumps({"servers": [{"command": "x"}]}))
    assert load_server_config() == []


# -- schema mapping ---------------------------------------------------------


def test_json_schema_becomes_exact_argument_types() -> None:
    required, optional, describes = schema_arguments(
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Where to look"},
                "depth": {"type": "integer"},
                "ratio": {"type": "number"},
                "deep": {"type": "boolean"},
                "extra": {"type": ["string", "null"]},
            },
            "required": ["path", "depth"],
        }
    )
    assert required == {"path": str, "depth": int}
    assert optional == {"ratio": float, "deep": bool, "extra": str}
    # The server wrote this for the model choosing a value; it used to be
    # read for its type and then thrown away.
    assert describes == {"path": "Where to look"}


def test_a_missing_or_odd_schema_is_not_a_crash() -> None:
    assert schema_arguments(None) == ({}, {}, {})
    assert schema_arguments({"type": "object"}) == ({}, {}, {})
    assert schema_arguments({"properties": {"x": None}}) == ({}, {"x": str}, {})


# -- policy -----------------------------------------------------------------


def test_a_third_party_tool_is_sensitive_unless_it_says_read_only() -> None:
    bridge, _ = bridge_with(
        [tool("read_docs", read_only=True), tool("delete_everything", read_only=False)]
    )
    registry = ToolRegistry()
    register_mcp_tools(registry, bridge)
    specs = {s.name: s for s in registry}

    assert specs["mcp__docs__read_docs"].sensitive is False
    assert specs["mcp__docs__delete_everything"].sensitive is True


def test_tool_names_are_namespaced_by_server() -> None:
    bridge, _ = bridge_with([tool("search")], name="corp")
    registry = ToolRegistry()
    register_mcp_tools(registry, bridge)
    assert [s.name for s in registry] == ["mcp__corp__search"]


def test_a_dead_server_does_not_stop_registration() -> None:
    bridge, _ = bridge_with([tool("x")], fail=True)
    registry = ToolRegistry()
    register_mcp_tools(registry, bridge)

    assert len(registry) == 0
    assert bridge.list_tools()[0]["error"]


def test_calling_an_unknown_server_is_refused() -> None:
    bridge, _ = bridge_with([tool("x")])
    with pytest.raises(McpUnavailableError, match="no MCP server"):
        bridge.call("nope", "x", {})


def test_arguments_outside_the_declared_schema_are_refused() -> None:
    schema = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
    bridge, _ = bridge_with([tool("search", schema=schema, read_only=True)])
    registry = ToolRegistry()
    register_mcp_tools(registry, bridge)
    spec = next(iter(registry))

    assert registry.validate(spec, {"q": "hello"}) == {"q": "hello"}
    with pytest.raises(InvalidArgumentsError):
        registry.validate(spec, {"q": "hello", "sneaky": "rm -rf"})
    with pytest.raises(InvalidArgumentsError):
        registry.validate(spec, {})


# -- routing ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_output_is_enveloped_and_write_tools_are_confirmed(tmp_path) -> None:
    schema = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
    bridge, session = bridge_with(
        [
            tool("lookup", schema=schema, read_only=True),
            tool("mutate", schema=schema, read_only=False),
        ]
    )
    registry = ToolRegistry()
    register_mcp_tools(registry, bridge)
    app = create_app(
        version="0.1.0-test",
        runtime=RuntimeStore(audit_path=tmp_path / "audit.jsonl"),
        tools=registry,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as c:
        read = await c.post("/tools/mcp__docs__lookup", json={"arguments": {"q": "x"}})
        write = await c.post("/tools/mcp__docs__mutate", json={"arguments": {"q": "x"}})

    assert read.json()["status"] == "executed"
    # Another program's output is untrusted content like any other.
    assert "UNTRUSTED" in read.json()["result"]["text"]
    assert "ran lookup" in read.json()["result"]["text"]
    assert write.json()["status"] == "confirmation_required"
    assert session.calls == [("lookup", {"q": "x"})]
