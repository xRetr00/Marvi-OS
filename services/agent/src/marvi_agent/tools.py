"""Voice-side bridge to the Marvi Gateway tool router.

The agent never touches a device or a sidecar directly. It asks the Gateway,
and the Gateway decides whether the action runs now or needs a confirmation
token. Spoken approval resolves the *same* token the Dynamic Island resolves,
with the same exact arguments, so the two approval paths cannot diverge.

Verified against livekit-agents 1.6.10: `@function_tool` builds the schema from
type hints and the docstring, `RunContext` is excluded from that schema, and a
`ToolError` message is surfaced to the LLM.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from livekit.agents import RunContext, ToolError, function_tool

log = logging.getLogger("marvi.voice")

DEFAULT_GATEWAY_URL = "http://127.0.0.1:8765"
REQUEST_TIMEOUT = 12.0


def gateway_base_url() -> str:
    return os.environ.get("MARVI_GATEWAY_URL", DEFAULT_GATEWAY_URL).rstrip("/")


#: How much of a tool result the model gets. Long enough for search results to
#: be usable, short enough that nothing reads a page aloud.
MAX_RESULT_CHARS = 900

#: Keys that say a call worked rather than what it answered.
#:
#: "ok True" is not an answer, it is the absence of one, and reading it out is
#: worse than saying "Done." -- which is what a tool that succeeded and returned
#: nothing has actually done.
BOOKKEEPING = frozenset({"ok", "success", "status", "accepted", "applied", "changed"})


def describe(result: Any) -> str:
    """What the model is told a tool returned.

    Everything that was not a room state used to come back as the literal
    string "Done." -- the result was thrown away before the model ever saw it.
    That was survivable while voice had five hand-written tools whose answers
    were room state or nothing, and it broke the moment the Gateway's whole
    catalogue came through here: a web search returned "Done.", which the model
    read as confirmation of whatever it had already guessed, and said so.

    So: render it. Compactly, because a spoken turn should not read JSON aloud,
    but render it -- a tool whose answer is discarded is worse than a tool that
    does not exist, because the model believes it worked.
    """
    if isinstance(result, dict):
        state = result.get("state")
        if isinstance(state, dict):
            light = state.get("light") or {}
            modes = state.get("modes") or {}
            presence = state.get("presence") or {}
            freshness = "live" if result.get("live") else "last known"
            lit = (
                f"on at {light.get('brightness', '?')} percent"
                if light.get("on")
                else "off"
            )
            return (
                f"Room ({freshness}): light {lit}, mode {modes.get('active_mode', 'unknown')}, "
                f"{'someone is present' if presence.get('detected') else 'nobody detected'}."
            )
    rendered = _render(result)
    return rendered[:MAX_RESULT_CHARS] if rendered else "Done."


def _render(value: Any, depth: int = 0) -> str:
    """A value as a short line of prose. Depth-bounded against nested results."""
    if value is None or value == "" or value == [] or value == {}:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool | int | float):
        return str(value)
    if depth > 2:
        return ""
    if isinstance(value, list):
        parts = [_render(item, depth + 1) for item in value[:5]]
        return "; ".join(part for part in parts if part)
    if isinstance(value, dict):
        # The common shape from a search or a listing: the payload is one key
        # and the rest is bookkeeping.
        for key in ("results", "items", "entries", "text", "content", "answer"):
            if key in value:
                inner = _render(value[key], depth + 1)
                if inner:
                    return inner
        parts = [
            f"{key} {_render(item, depth + 1)}"
            for key, item in list(value.items())[:6]
            if key not in BOOKKEEPING and _render(item, depth + 1)
        ]
        return ", ".join(parts)
    return str(value)


class GatewayTools:
    """Session-scoped tool surface. One instance per voice session."""

    def __init__(self, base_url: str | None = None, client: httpx.AsyncClient | None = None):
        self._base_url = (base_url or gateway_base_url()).rstrip("/")
        self._client = client
        # The single action awaiting a spoken yes or no, with the arguments the
        # Gateway issued the token for. Never mutated between issue and approval.
        self._pending: tuple[str, dict[str, Any]] | None = None

    @property
    def pending_token(self) -> str | None:
        return self._pending[0] if self._pending else None

    async def _post(self, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        client = self._client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
        try:
            response = await client.post(f"{self._base_url}{path}", json=payload)
            try:
                body = response.json()
            except ValueError:
                body = {}
            return response.status_code, body
        except httpx.HTTPError as exc:
            raise ToolError(f"Marvi Gateway is unreachable: {exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()

    async def _call(self, tool: str, arguments: dict[str, Any]) -> str:
        status, body = await self._post(f"/tools/{tool}", {"arguments": arguments})
        if status == 404:
            raise ToolError(f"{tool} is not available.")
        if status == 422:
            raise ToolError(str(body.get("detail", "those arguments are not valid")))
        if status != 200:
            raise ToolError(f"{tool} failed with status {status}.")

        outcome = body.get("status")
        if outcome == "confirmation_required":
            self._pending = (str(body["token"]), arguments)
            return (
                "That action needs confirmation. Ask the user to approve, then call "
                "approve_pending_action or deny_pending_action."
            )
        if outcome == "failed":
            raise ToolError(str(body.get("error", "the action failed")))
        return describe(body.get("result"))

    # -- room tools ---------------------------------------------------------

    @function_tool
    async def room_state(self, context: RunContext) -> str:
        """Read the current smart room state: light, mode, and presence."""
        return await self._call("room_state", {})

    @function_tool
    async def room_light(
        self,
        context: RunContext,
        on: bool,
        brightness: int | None = None,
        color_temp: int | None = None,
    ) -> str:
        """Turn the room light on or off, optionally at a brightness from 1 to 100
        and a colour temperature from 2700 (warm) to 6500 (cool) kelvin."""
        arguments: dict[str, Any] = {"on": on}
        if brightness is not None:
            arguments["brightness"] = brightness
        if color_temp is not None:
            arguments["color_temp"] = color_temp
        return await self._call("room_set_light", arguments)

    @function_tool
    async def room_mode(self, context: RunContext, mode: str) -> str:
        """Change the room mode. One of normal, reading, focus, relax, night, sleep, alarm, off."""
        return await self._call("room_set_mode", {"mode": mode})

    # -- world context ------------------------------------------------------

    @function_tool
    async def recall(self, context: RunContext, query: str) -> str:
        """Search what Marvi remembers about a person, topic, or past event."""
        status, body = await self._post("/tools/memory_search", {"arguments": {"query": query}})
        if status != 200 or body.get("status") != "executed":
            raise ToolError("Memory is unavailable right now.")
        results = (body.get("result") or {}).get("results") or []
        if not results:
            return f"Nothing remembered about {query}."
        return " ".join(f"{r['subject']}: {r['body']}" for r in results[:3])[:600]

    @function_tool
    async def remember(self, context: RunContext, subject: str, body: str) -> str:
        """Remember a durable fact the user has told you."""
        return await self._call("memory_remember", {"subject": subject, "body": body})

    # -- spoken approval ----------------------------------------------------

    async def _resolve(self, decision: str) -> tuple[int, dict[str, Any]]:
        if self._pending is None:
            raise ToolError("There is no action waiting for approval.")
        token, arguments = self._pending
        status, body = await self._post(
            f"/confirmations/{token}", {"decision": decision, "arguments": arguments}
        )
        # The token is spent either way; the Island may also have resolved it first.
        self._pending = None
        return status, body

    @function_tool
    async def approve_pending_action(self, context: RunContext) -> str:
        """Approve the action currently waiting for confirmation. Only after the user says yes."""
        status, body = await self._resolve("approve")
        if status == 404:
            raise ToolError("That confirmation already expired or was already answered.")
        if status == 409:
            raise ToolError("The action changed since it was requested, so it was blocked.")
        if status != 200:
            raise ToolError(f"The approval failed with status {status}.")
        if body.get("status") == "failed":
            raise ToolError(str(body.get("error", "the action failed")))
        return describe(body.get("result"))

    @function_tool
    async def deny_pending_action(self, context: RunContext) -> str:
        """Deny the action currently waiting for confirmation."""
        status, _ = await self._resolve("deny")
        if status == 404:
            raise ToolError("That confirmation already expired or was already answered.")
        return "Cancelled."

    def as_list(self) -> list[Any]:
        """The hand-written tools: the room, memory, and the confirmation pair.

        These are written out rather than discovered because their wording is
        tuned for speech -- a spoken "turn the light on" should not have to
        survive a schema written for a typed interface.
        """
        return [
            self.room_state,
            self.room_light,
            self.room_mode,
            self.recall,
            self.remember,
            self.approve_pending_action,
            self.deny_pending_action,
        ]

    #: Tools the Agent already words better itself, or that make no sense spoken.
    #:
    #: The room and memory tools below are hand-written for speech. Anything
    #: needing a file path or a URL read aloud is not a spoken tool at all.
    SPOKEN_BADLY = frozenset(
        {
            "room_state",
            "room_set_light",
            "room_set_mode",
            "memory_search",
            "memory_remember",
            "memory_forget",
            "web_fetch",
        }
    )

    async def from_gateway(self) -> list[Any]:
        """Every other tool the Gateway has, built from its own catalogue.

        Voice had seven tools and chat had seventeen, maintained by hand in two
        places -- so asking Marvi out loud to search the web got "I don't have a
        web search tool", truthfully, while the same question typed worked. Any
        tool added since, and every MCP server, reached one surface only.

        Built from `/tools` rather than duplicated again: the Gateway already
        publishes each tool's schema for exactly this, and every call goes back
        through `/tools/{name}`, which is the one path with the confirmation
        flow and the audit line on it.

        Never raises. Voice with the seven it wrote itself is worse than voice
        with all of them, and far better than no voice at all.
        """
        from livekit.agents import function_tool

        client = self._client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
        try:
            response = await client.get(f"{self._base_url}/tools")
            response.raise_for_status()
            catalogue = response.json().get("tools") or []
        except Exception as exc:
            log.warning("could not read the tool catalogue: %s", exc)
            return []
        finally:
            if self._client is None:
                await client.aclose()

        built: list[Any] = []
        for entry in catalogue:
            name = str(entry.get("name") or "")
            if not name or name in self.SPOKEN_BADLY:
                continue
            required = [a for a in (entry.get("arguments") or []) if isinstance(a, str)]
            optional = [a for a in (entry.get("optional") or []) if isinstance(a, str)]

            def caller(raw_arguments: dict[str, Any], _name: str = name) -> Any:
                return self._call(_name, raw_arguments)

            built.append(
                function_tool(
                    caller,
                    raw_schema={
                        "name": name,
                        "description": str(entry.get("description") or name),
                        "parameters": {
                            "type": "object",
                            # The Gateway reports argument names and which are
                            # required. It does not report their types here, and
                            # a string the handler coerces beats a type invented
                            # on this side and rejected on the other.
                            "properties": {
                                argument: {"type": "string"}
                                for argument in [*required, *optional]
                            },
                            "required": required,
                        },
                    },
                )
            )
        log.info("%d tools from the Gateway, on top of the spoken ones", len(built))
        return built
