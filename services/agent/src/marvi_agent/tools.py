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

import asyncio
import logging
import os
import time
from typing import Any

import httpx
from livekit.agents import RunContext, ToolError, function_tool
from livekit.agents.llm import ToolFlag

log = logging.getLogger("marvi.voice")

DEFAULT_GATEWAY_URL = "http://127.0.0.1:8765"
#: Mirrors the Gateway's CONFIRMATION_TTL_SECONDS. A token it has already
#: expired must not go on blocking the next request here.
CONFIRMATION_TTL = 120.0
REQUEST_TIMEOUT = 12.0
#: How a job that takes minutes is watched. Polled rather than pushed
#: because the Gateway holds these in memory and a socket per job would be
#: infrastructure for a thing that finishes.
POLL_EVERY = 3.0
AWAIT_TIMEOUT = 1800.0
#: Sparse on purpose: this talks over a conversation that has moved on.
FILLER_AFTER = 25.0
FILLER_EVERY = 90.0


def gateway_base_url() -> str:
    return os.environ.get("MARVI_GATEWAY_URL", DEFAULT_GATEWAY_URL).rstrip("/")


#: How much of a tool result the model gets. Long enough for search results to
#: be usable, short enough that nothing reads a page aloud.
MAX_RESULT_CHARS = 900

#: How many items of a list the model is shown. A directory listing is the
#: common case and its entries are short, so this is generous enough to cover
#: one; whatever it does not cover is counted rather than dropped, and the
#: character budget above is the real limit.
MAX_LIST_ITEMS = 12

#: Said out loud rather than left to be inferred from a sentence that stops.
CUT_SHORT = " ... (cut short)"

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
            lit = f"on at {light.get('brightness', '?')} percent" if light.get("on") else "off"
            return (
                f"Room ({freshness}): light {lit}, mode {modes.get('active_mode', 'unknown')}, "
                f"{'someone is present' if presence.get('detected') else 'nobody detected'}."
            )
    rendered = _render(result)
    if not rendered:
        return "Done."
    # Marked, for the same reason. A result cut at nine hundred characters
    # without saying so is read as a complete one.
    if len(rendered) > MAX_RESULT_CHARS:
        # Inside the budget, not on top of it: the cap is what keeps a spoken
        # turn from reading a web page aloud.
        return rendered[: MAX_RESULT_CHARS - len(CUT_SHORT)] + CUT_SHORT
    return rendered


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
        parts = [_render(item, depth + 1) for item in value[:MAX_LIST_ITEMS]]
        shown = "; ".join(part for part in parts if part)
        left = len(value) - MAX_LIST_ITEMS
        # Saying how many were dropped is the whole difference between a short
        # answer and a wrong one.
        #
        # This cut a 28-entry directory listing to its first five, all of them
        # dot-directories, and said nothing. Marvi read that as the directory
        # and told the user their file was not there and the workspace looked
        # unfamiliar -- which was an accurate report of what she had been
        # given. An hour went into the file tools; the file tools were fine.
        return f"{shown} (and {left} more)" if left > 0 and shown else shown
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
        #: When that token was issued. One slot means a second sensitive call
        #: while one is outstanding used to overwrite it silently, so a spoken
        #: "yes" approved whichever token arrived last rather than the action
        #: the user had just been told about. Now the second call is refused
        #: while the first is still live, and the Gateway's own 120s expiry is
        #: what releases the slot if nobody ever answers.
        self._pending_at = 0.0

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
            if self._pending is not None and time.monotonic() - self._pending_at < CONFIRMATION_TTL:
                # Refused rather than queued. Two actions waiting on one spoken
                # "yes" is ambiguous to the user as well as to the code, and
                # the answer is to settle one before asking about the other.
                return (
                    "Another action is already waiting for the user to approve or deny it. "
                    "Settle that one first, then ask again."
                )
            self._pending = (str(body["token"]), arguments)
            self._pending_at = time.monotonic()
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
        status, body = await self._post("/tools/memory_recall", {"arguments": {"query": query}})
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

    # -- work that takes minutes ---------------------------------------------

    @function_tool(
        flags=ToolFlag.CANCELLABLE,
        # Asked twice for the same job -- which happens, because people repeat
        # themselves when an answer is slow -- the second call is refused
        # rather than starting a second wait on the same work.
        on_duplicate="reject",
        duplicate_scope="name_and_args",
    )
    async def await_delegated(self, context: RunContext, job: str) -> str:
        """Wait for a delegated coding job and report what came back.

        Call this straight after delegating. It does not block the
        conversation: the first progress update hands control back to the model
        immediately, and the result arrives on its own whenever the job
        finishes.

        Args:
            job: The job id that delegate_to_coder returned.
        """
        # This is the whole mechanism. `update` releases control to the LLM
        # with this sentence as the tool's synthetic return, so Marvi says it
        # and carries on talking while the body below keeps running. The
        # eventual `return` is delivered into the conversation whenever it
        # lands.
        await context.update(f"Working on job {job} now, I will say when it is done.")

        # And a word during the quiet stretches, so a five-minute job does not
        # feel like a dropped call. Deliberately sparse: this interrupts a
        # conversation that has moved on to something else.
        async with context.with_filler(
            "Still waiting on that job.", delay=FILLER_AFTER, interval=FILLER_EVERY
        ):
            deadline = time.monotonic() + AWAIT_TIMEOUT
            while time.monotonic() < deadline:
                status, body = await self._post(
                    "/tools/delegated_status", {"arguments": {"job": job}}
                )
                if status != 200:
                    raise ToolError(f"could not check job {job}")
                result = body.get("result") or {}
                if not result.get("ok"):
                    raise ToolError(str(result.get("detail", f"no job {job}")))
                if result.get("state") != "running":
                    return describe(result)
                await asyncio.sleep(POLL_EVERY)

        return (
            f"Job {job} is still running after {AWAIT_TIMEOUT // 60} minutes. "
            "It has not been stopped; check it again later with delegated_status."
        )

    async def _resolve(self, decision: str) -> tuple[int, dict[str, Any]]:
        if self._pending is None:
            raise ToolError("There is no action waiting for approval.")
        token, arguments = self._pending
        status, body = await self._post(
            f"/confirmations/{token}", {"decision": decision, "arguments": arguments}
        )
        # The token is spent either way; the Island may also have resolved it first.
        self._pending = None
        self._pending_at = 0.0
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
        """The hand-written tools: the room, memory, the confirmation pair, and
        the one that waits.

        These are written out rather than discovered because their wording is
        tuned for speech -- a spoken "turn the light on" should not have to
        survive a schema written for a typed interface. `await_delegated` is
        here for a different reason: it is an async tool, and the generic
        bridge in `from_gateway` cannot build one of those from a JSON schema.
        """
        return [
            self.room_state,
            self.room_light,
            self.room_mode,
            self.recall,
            self.remember,
            self.approve_pending_action,
            self.deny_pending_action,
            self.await_delegated,
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
            "memory_recall",
            "memory_remember",
            "memory_forget",
            "web_fetch",
        }
    )

    async def context_blocks(self) -> list[str]:
        """Prompt text the Gateway holds and the voice worker cannot see.

        The same problem `from_gateway` solved for tools, one level up. Voice
        writes its own instructions in this process, so everything the Gateway
        assembles for the typed surface -- which skills exist, where Marvi is
        installed -- reached chat and not speech. Published rather than
        duplicated, so the two cannot drift again.

        Never raises: a Gateway that cannot answer costs Marvi her skill
        catalogue, not her voice.
        """
        client = self._client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
        try:
            response = await client.get(f"{self._base_url}/context")
            response.raise_for_status()
            blocks = response.json().get("blocks") or []
            return [str(block) for block in blocks if str(block).strip()]
        except Exception as exc:
            log.warning("could not read the prompt context: %s", exc)
            return []
        finally:
            if self._client is None:
                await client.aclose()

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
            published_schema = entry.get("input_schema")
            parameters = (
                published_schema
                if isinstance(published_schema, dict) and published_schema.get("type") == "object"
                else {
                    "type": "object",
                    "properties": {
                        argument: {"type": "string"} for argument in [*required, *optional]
                    },
                    "required": required,
                }
            )

            def caller(raw_arguments: dict[str, Any], _name: str = name) -> Any:
                return self._call(_name, raw_arguments)

            built.append(
                function_tool(
                    caller,
                    raw_schema={
                        "name": name,
                        "description": str(entry.get("description") or name),
                        "parameters": parameters,
                    },
                )
            )
        log.info("%d tools from the Gateway, on top of the spoken ones", len(built))
        return built
