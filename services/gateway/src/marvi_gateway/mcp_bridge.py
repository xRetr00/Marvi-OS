"""MCP servers, routed through the Gateway rather than attached to the agent.

LiveKit can attach MCP servers directly to an `Agent`, which is simpler — but
tools reached that way never touch the Gateway, so they get no confirmation
token, no audit line, and no idempotency. ADR-008 says every action Marvi takes
on the world goes through one policy, so MCP is a client here instead.

An MCP tool is treated as sensitive unless its own annotations declare it a
read-only hint: an unknown third-party tool asking to act should ask first.

Servers are declared in JSON, either inline via `MARVI_MCP_SERVERS` or in a file
named by `MARVI_MCP_CONFIG`:

    {"servers": [
        {"name": "docs", "command": "npx", "args": ["-y", "some-mcp-server"]},
        {"name": "remote", "url": "https://example.com/mcp"}
    ]}
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path
from typing import Any

from .untrusted import wrap_external

CALL_TIMEOUT = 60.0

# JSON Schema -> the registry's exact-argument types. Anything unrecognised is
# accepted as a string, which keeps validation strict without guessing.
JSON_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def schema_arguments(schema: Any) -> tuple[dict[str, type], dict[str, type]]:
    """Split an MCP inputSchema into required and optional argument types."""
    if not isinstance(schema, dict):
        return {}, {}
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}, {}
    required_names = {n for n in (schema.get("required") or []) if isinstance(n, str)}
    required: dict[str, type] = {}
    optional: dict[str, type] = {}
    for name, definition in properties.items():
        declared = (definition or {}).get("type") if isinstance(definition, dict) else None
        if isinstance(declared, list):  # e.g. ["string", "null"]
            declared = next((d for d in declared if d != "null"), None)
        python_type = JSON_TYPES.get(declared or "", str)
        (required if name in required_names else optional)[name] = python_type
    return required, optional


class McpUnavailableError(Exception):
    pass


def load_server_config() -> list[dict[str, Any]]:
    raw = os.environ.get("MARVI_MCP_SERVERS", "").strip()
    if not raw:
        configured = os.environ.get("MARVI_MCP_CONFIG", "").strip()
        if configured and Path(configured).is_file():
            raw = Path(configured).read_text(encoding="utf-8")
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    servers = parsed.get("servers") if isinstance(parsed, dict) else parsed
    return [s for s in (servers or []) if isinstance(s, dict) and s.get("name")]


class _LoopThread:
    """A private event loop so synchronous tool handlers can drive async MCP
    sessions without the Gateway becoming async end to end."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True, name="marvi-mcp")
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro, timeout: float = CALL_TIMEOUT):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)


class McpBridge:
    """Connects to configured MCP servers and exposes their tools."""

    def __init__(self, servers: list[dict[str, Any]] | None = None, session_factory: Any = None):
        self.servers = servers if servers is not None else load_server_config()
        self._factory = session_factory
        self._loop: _LoopThread | None = None
        self._sessions: dict[str, Any] = {}

    def available(self) -> bool:
        return bool(self.servers)

    def _ensure_loop(self) -> _LoopThread:
        if self._loop is None:
            self._loop = _LoopThread()
        return self._loop

    def close(self) -> None:
        if self._loop is not None:
            self._loop.stop()
            self._loop = None

    async def _connect(self, spec: dict[str, Any]) -> Any:
        if self._factory is not None:
            return await self._factory(spec)
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        if "command" not in spec:
            raise McpUnavailableError(
                f"{spec['name']}: only stdio servers are wired; give it a command"
            )
        params = StdioServerParameters(
            command=spec["command"], args=spec.get("args") or [], env=spec.get("env")
        )
        streams = await stdio_client(params).__aenter__()
        session = ClientSession(*streams)
        await session.__aenter__()
        await session.initialize()
        return session

    def _session(self, spec: dict[str, Any]) -> Any:
        name = spec["name"]
        if name not in self._sessions:
            self._sessions[name] = self._ensure_loop().submit(self._connect(spec))
        return self._sessions[name]

    def list_tools(self) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for spec in self.servers:
            try:
                session = self._session(spec)
                listing = self._ensure_loop().submit(session.list_tools())
            except Exception as exc:
                found.append({"server": spec["name"], "error": str(exc)[:160], "tools": []})
                continue
            found.append(
                {
                    "server": spec["name"],
                    "error": None,
                    "tools": [
                        {
                            "name": t.name,
                            "description": (t.description or "")[:200],
                            "read_only": bool(
                                getattr(getattr(t, "annotations", None), "readOnlyHint", False)
                            ),
                            "schema": getattr(t, "inputSchema", None),
                        }
                        for t in getattr(listing, "tools", []) or []
                    ],
                }
            )
        return found

    def call(self, server: str, tool: str, arguments: dict[str, Any]) -> Any:
        spec = next((s for s in self.servers if s["name"] == server), None)
        if spec is None:
            raise McpUnavailableError(f"no MCP server named {server}")
        session = self._session(spec)
        result = self._ensure_loop().submit(session.call_tool(tool, arguments))
        parts = []
        for block in getattr(result, "content", []) or []:
            parts.append(getattr(block, "text", None) or str(block))
        return {"content": parts, "is_error": bool(getattr(result, "isError", False))}


def register_mcp_tools(registry, bridge: McpBridge) -> None:
    """Register every discovered MCP tool under `mcp__<server>__<tool>`.

    A third-party tool is sensitive unless it declares a read-only hint, so an
    unfamiliar server cannot act without the user seeing it first.
    """
    from .tools import ToolSpec

    for entry in bridge.list_tools():
        server = entry["server"]
        for tool in entry["tools"]:
            name = f"mcp__{server}__{tool['name']}"
            required, optional = schema_arguments(tool.get("schema"))

            def handler(_server=server, _tool=tool["name"], **arguments):
                result = bridge.call(_server, _tool, arguments)
                # Another program's output is untrusted content like any other.
                return wrap_external(f"mcp:{_server}:{_tool}", result).model_dump()

            registry.register(
                ToolSpec(
                    name=name,
                    description=tool["description"] or f"{server} {tool['name']}",
                    arguments=required,
                    optional=optional,
                    sensitive=not tool["read_only"],
                    handler=handler,
                )
            )
