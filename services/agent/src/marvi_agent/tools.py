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

#: How long a tool call may run in silence before Marvi says she is on it.
#:
#: Measured against the pipeline it sits in: `llm ttft` is 578ms at the median,
#: so a filler firing earlier than that would talk over ordinary turns. At 0.9s
#: it stays out of the way of every fast call and covers the ones a listener
#: would otherwise read as a dropped line.
FILLER_DELAY = 0.9

#: Said, rather than generated. A fixed line cannot be truncated by the tool
#: call the way the model's own narration was, and it is deliberately vague
#: about what is being done: it fires before the result exists, so anything
#: more specific would be a guess spoken aloud.
THINKING = "One sec."


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

#: The Gateway's own name for the tool that finds the others. Named here rather
#: than matched by string in three places.
SEARCH_TOOL = "tool_search"

#: Said out loud rather than left to be inferred from a sentence that stops.
CUT_SHORT = " ... (cut short)"

#: Keys that say a call worked rather than what it answered.
#:
#: "ok True" is not an answer, it is the absence of one, and reading it out is
#: worse than saying "Done." -- which is what a tool that succeeded and returned
#: nothing has actually done.
BOOKKEEPING = frozenset({"ok", "success", "status", "accepted", "applied", "changed"})


#: How an action reports itself back to the model.
#:
#: The fabrication problem outlived every rule written against it. Closed off
#: in the past tense -- "I've closed the browser" -- it came back in the future
#: tense -- "I'll close the browser" -- and in between it produced things like
#: "I ran memory_forget to remove notes about your projects" on a turn where
#: `memory_forget` had run four times, for "Shreef", "Sharif", "Keychron K2"
#: and "Keychron K10". Every word of that sentence was defensible and the whole
#: of it was false.
#:
#: A rule cannot fix that, because the model is not lying: it has no record to
#: check itself against. `describe` handed back a rendered value with nothing
#: in it saying which tool produced it or what it was asked to do, so "did I
#: close the browser?" was a question about its own memory of the last few
#: hundred tokens.
#:
#: So every call now comes back as a receipt: the tool, the arguments that were
#: actually sent, and whether it worked. This is the shape the literature calls
#: an execution-grounded claim -- the published version signs them so a
#: separate verifier can catch a forged one, which matters when something other
#: than the model reads them. Here the reader *is* the model, one turn later,
#: and what it needs is not proof against forgery but a record to point at.
#:
#: Failures get one too, and that is half the point. A tool that raised used to
#: reach the model as a bare sentence with no subject, so "it failed" and "I
#: did not try" were the same shape in the transcript.
RECEIPT = "[did {tool}{arguments} -> {outcome}]"

#: Arguments are what makes a receipt worth having. "I ran memory_forget" is
#: true of a turn that forgot the wrong thing; "did memory_forget query=Shreef"
#: is not. Bounded, because a receipt that quotes a file's contents back is a
#: second copy of the result.
MAX_ARGUMENT_CHARS = 90


def receipt(tool: str, arguments: dict[str, Any] | None, outcome: str, said: str = "") -> str:
    """One line saying what actually ran, in front of whatever it returned."""
    shown = ""
    if arguments:
        pairs = []
        for name, value in list(arguments.items())[:4]:
            rendered = _render(value, depth=2)
            if rendered:
                pairs.append(f"{name}={rendered}")
        if pairs:
            shown = " " + " ".join(pairs)[:MAX_ARGUMENT_CHARS]
    line = RECEIPT.format(tool=tool, arguments=shown, outcome=outcome)
    return f"{line} {said}".strip()


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


def _number(value: Any) -> int | None:
    """An optional integer argument as the model actually sends it.

    Asked to dim the light, the model filled the optional colour temperature
    in with the *string* "None". Pydantic refused it, the tool raised, and
    LiveKit retried -- four times, until `max_tool_steps` ran out and the turn
    ended with "generating final response with tool_choice='none'". The light
    never moved and Marvi had nothing to say about why.

    An optional argument a model declines to use is not an error worth losing
    a turn over, however it spells the declining. Anything that is not a
    number becomes the absence it was meant to be.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


#: Whether the catalogue is held behind `tool_search` instead of loaded. Off:
#: see `from_gateway` for the three sweeps that turned it off.
DEFER_SETTING = "MARVI_DEFER_TOOLS"


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
        #: Every tool the Gateway has, by name, whether or not it is loaded.
        #: Kept so a search can add one without another round trip.
        self._catalogue: dict[str, dict[str, Any]] = {}
        #: What the model can currently call. Grows when a search finds
        #: something; never shrinks, because a tool that worked a minute ago
        #: and has quietly gone is worse than one that was never there.
        self._loaded: set[str] = set()
        #: Set once the Agent exists, which is after these tools are built.
        self._agent: Any = None

    def attach(self, agent: Any) -> None:
        """Give these tools the Agent, so a search can add to it."""
        self._agent = agent

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

    async def _call(
        self, tool: str, arguments: dict[str, Any], context: RunContext | None = None
    ) -> str:
        """Run a Gateway tool, saying something if it takes long enough to notice.

        The persona forbids narrating a tool call, and that rule was measured:
        with thirteen tools in the request the model announced what it was
        about to do, and the announcement was cut off the moment the call
        began -- "Let me check what I know about this", then silence.

        The rule fixed the truncation and left the gap. LiveKit's own latency
        guidance names the missing half: use a thinking sound so nobody waits
        in silence. The difference from what the model was doing is that this
        is played by the framework, not generated, so a tool call cannot
        truncate it.

        `with_filler` fires only after the session has been *continuously
        idle* for `delay`, so a fast tool stays silent and only a call slow
        enough to sound like a dropped line ever says anything. Once per call:
        `interval` is left unset, because a tool this path runs is seconds at
        most -- the one that takes minutes is `await_delegated`, which sets
        its own.
        """
        if context is None:
            return await self._run(tool, arguments)
        async with context.with_filler(THINKING, delay=FILLER_DELAY, max_steps=1):
            return await self._run(tool, arguments)

    async def _run(self, tool: str, arguments: dict[str, Any]) -> str:
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
            # A receipt, not a bare sentence. "The action failed" with no
            # subject reads the same in a transcript as never having tried,
            # which is how a failed call became a confident report of success.
            raise ToolError(
                receipt(tool, arguments, "FAILED", str(body.get("error", "no reason given")))
            )

        result = body.get("result")
        if tool == SEARCH_TOOL and isinstance(result, dict):
            # The half of the search that matters. Telling the model a tool
            # exists and leaving it uncallable is worse than not having the
            # search: it produces a confident description of something that
            # then fails.
            found = [
                str(row.get("name"))
                for row in (result.get("tools") or [])
                if isinstance(row, dict) and row.get("name")
            ]
            await self._load_found(found)
        return receipt(tool, arguments, "ok", describe(result))

    # -- the bridge ---------------------------------------------------------
    #
    # `tool_call` is taken from Hermes Agent, which pairs `tool_search` with a
    # `tool_call` bridge rather than making the model do a two-step. Two things
    # measured here say the same thing.
    #
    # First, the model already emits it. Twice in one sweep LiveKit logged
    # `unknown AI function \`tool_call\`` -- the model reaching for a bridge
    # by the name the convention gave it, into nothing.
    #
    # Second, when the whole catalogue was named in the instructions but only
    # the core set was loaded, the model called the named tools directly and
    # LiveKit rejected ten of them, while `tool_search` -- the step that was
    # supposed to bridge that -- fired once in 123 turns. A model calls the
    # tool it can see named. Giving that call somewhere to land is cheaper
    # than teaching it not to make it.
    #
    # Costs one schema and is a no-op while nothing is deferred, which is why
    # it is safe to keep on: it only ever turns a rejection into a call.

    @function_tool
    async def tool_call(
        self, context: RunContext, name: str, arguments: dict[str, Any] | None = None
    ) -> str:
        """Call any tool by name, including one that is not currently loaded.
        Pass the tool's own name and its arguments.

        Use this when you know which tool you want. It is the same as calling
        the tool directly and always works, even for tools you cannot see.
        """
        wanted = str(name or "").strip()
        if not wanted:
            raise ToolError("A tool name is required.")
        if wanted not in self._catalogue:
            near = [known for known in sorted(self._catalogue) if wanted in known]
            return (
                f"There is no tool called {wanted!r}."
                + (f" Did you mean {near[0]!r}?" if near else "")
                + f" Use {SEARCH_TOOL} with a word or two to find the right one."
            )
        # Loaded on the way through, so the next call goes direct and this
        # one does not have to come back here.
        if wanted not in self._loaded:
            await self._load_found([wanted])
        return await self._call(wanted, dict(arguments or {}), context)

    # -- room tools ---------------------------------------------------------

    @function_tool
    async def room_state(self, context: RunContext) -> str:
        """Read the current smart room state: light, mode, and presence."""
        return await self._call("room_state", {}, context)

    @function_tool
    async def room_light(
        self,
        context: RunContext,
        on: bool,
        brightness: int | str | None = None,
        color_temp: int | str | None = None,
    ) -> str:
        """Turn the room light on or off, optionally at a brightness from 1 to 100
        and a colour temperature from 2700 (warm) to 6500 (cool) kelvin."""
        arguments: dict[str, Any] = {"on": on}
        if (level := _number(brightness)) is not None:
            arguments["brightness"] = level
        if (kelvin := _number(color_temp)) is not None:
            arguments["color_temp"] = kelvin
        return await self._call("room_set_light", arguments, context)

    @function_tool
    async def room_mode(self, context: RunContext, mode: str) -> str:
        """Change the room mode. One of normal, reading, focus, relax, night, sleep, alarm, off."""
        return await self._call("room_set_mode", {"mode": mode}, context)

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
        return await self._call("memory_remember", {"subject": subject, "body": body}, context)

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
            # `memory_forget` and `web_fetch` used to be here and had no
            # hand-written replacement, so voice simply could not do either.
            # Every other name on this list is dropped *because* a better one
            # is written below it; these two were dropped into nothing.
            #
            # The visible cost, from a sweep: "Forget that I use Zed." -> "I've
            # removed the note about you using Zed." She had no tool, so
            # instead of saying she could not, she said she had. A capability
            # removed without a replacement does not read as a missing
            # capability to the model -- it reads as one it must be able to do
            # somehow, and inventing the result is how that resolves.
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

    def _as_function_tool(self, entry: dict[str, Any]) -> Any:
        """One catalogue entry as a LiveKit function tool.

        Every call goes back through `/tools/{name}`, which is the one path
        with the confirmation flow and the audit line on it.
        """
        from livekit.agents import function_tool

        name = str(entry.get("name") or "")
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

        # `context` is annotated so LiveKit injects it: it resolves RunContext
        # parameters by type hint for raw-schema tools exactly as it does for
        # decorated ones (`llm/utils.py`, "inject RunContext (or subclasses)
        # if needed"). Without it every Gateway tool -- which is most of them
        # -- would run in silence while only the hand-written few could speak.
        # Defaulted, because injection is conditional: LiveKit skips it when
        # there is no call context, and a required parameter then fails the
        # bind rather than running the tool. The annotation is what selects it
        # for injection; the default is what survives its absence.
        def caller(
            raw_arguments: dict[str, Any],
            context: RunContext = None,  # type: ignore[assignment]
            _name: str = name,
        ) -> Any:
            return self._call(_name, raw_arguments, context)

        return function_tool(
            caller,
            raw_schema={
                "name": name,
                "description": str(entry.get("description") or name),
                "parameters": parameters,
            },
        )

    async def from_gateway(self, everything: bool | None = None) -> list[Any]:
        """The tools voice starts with: the core set, and the way to find the rest.

        Voice had seven tools and chat had seventeen, maintained by hand in two
        places -- so asking Marvi out loud to search the web got "I don't have a
        web search tool", truthfully, while the same question typed worked.
        Building from `/tools` fixed that and then overshot: fifty-six tools,
        five thousand tokens of schema, in front of the model on every turn
        including the ones that are somebody saying good morning.

        Past thirty to fifty tools a model's ability to pick the right one
        degrades -- that is Anthropic's published number, and it is a plain
        mechanical account of "most of the tools do not work" that has nothing
        to do with which model is answering.

        So the Gateway marks a core set, that is what loads, and the rest are
        found with `tool_search` and added mid-session. The whole catalogue is
        kept here so adding one later costs nothing.

        Never raises. Voice with the seven it wrote itself is worse than voice
        with all of them, and far better than no voice at all.
        """
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

        self._catalogue = {
            str(entry.get("name") or ""): entry
            for entry in catalogue
            if str(entry.get("name") or "") and str(entry.get("name")) not in self.SPOKEN_BADLY
        }
        # A Gateway that names no core set is one that does not know about
        # deferring, and the answer there is every tool rather than none.
        # Reading "no tool said it was core" as "nothing is core" would leave
        # voice with one tool against an older Gateway -- absence of the flag
        # is a fact about the Gateway, not about the tools.
        # Deferring is off by default now, and the reason is three sweeps of
        # the same 123 turns.
        #
        # It was on because past thirty to fifty tools a model picks worse --
        # Anthropic's published number, cited rather than measured here. What
        # measurement found was the other side of the ledger. Deferred, Marvi
        # refused twenty-three things she can do. Given the names of all
        # sixty-one in her instructions she stopped refusing and started
        # calling them by name, directly, the way a model does with any tool
        # it can see -- and LiveKit answered `unknown AI function` ten times,
        # because a named tool with no schema loaded is not callable. The
        # two-step dance was never going to hold: `tool_search` was called
        # once in 123 turns while ten direct calls were rejected.
        #
        # Loaded outright, the same script reached eighteen distinct tools
        # against fifteen attempted, with zero unknown functions, no narration,
        # and no sign of the degraded picking the deferral was guarding
        # against. It cost 0.1s at the median and 0.9s at p90.
        #
        # `MARVI_DEFER_TOOLS=on` is the way back, and `MARVI_CORE_TOOLS` still
        # chooses what survives when it is.
        if everything is None:
            everything = os.environ.get(DEFER_SETTING, "off").strip().lower() in (
                "0", "false", "no", "off", ""
            )
        defers = not everything and any(
            entry.get("core") for entry in self._catalogue.values()
        )
        self._loaded = {
            name
            for name, entry in self._catalogue.items()
            if not defers or entry.get("core") or name == SEARCH_TOOL
        }
        loaded = [self._as_function_tool(self._catalogue[name]) for name in self._loaded]
        if defers:
            log.info(
                "%d of %d Gateway tools loaded; the rest are found with %s",
                len(loaded),
                len(self._catalogue),
                SEARCH_TOOL,
            )
        else:
            log.info("%d tools from the Gateway, which names no core set", len(loaded))
        return loaded

    def catalogue_index(self) -> str:
        """Every tool's name, for the instructions. Names only, never schemas.

        Deferring the schemas worked and then failed in a way nothing was
        watching for. Measured over 123 real turns: seven distinct tools
        called, `tool_search` called once, and twenty-three straight refusals
        of things Marvi can do --

            "I can't open websites in a browser right now."      browser_open
            "I can't create cron jobs right now."                cronjob
            "I don't have access to your calendar."              calendar_events
            "I can't install skills right now."                  skill_install
            "I can't delegate coding tasks right now."           delegate_to_coder

        -- each phrased as a fact about herself, none of them true. A rule in
        the persona telling her to search first had already been added and did
        not fire, because a model cannot decide to look for a thing whose
        existence it has no reason to suspect. Twelve tools were in front of
        it and forty-nine were nowhere.

        Names are what closes that. The schemas are the expensive half -- the
        whole catalogue is roughly five thousand tokens of them, which is what
        deferring exists to avoid -- while sixty-one names cost a few hundred
        and are the entire difference between "I can't" and knowing there is
        something to look up. Grouped by the prefix the Gateway already names
        them with, so the list reads as areas rather than as sixty-one
        unrelated strings.
        """
        if not self._catalogue:
            return ""
        areas: dict[str, list[str]] = {}
        for name in sorted(self._catalogue):
            if name == SEARCH_TOOL:
                continue
            head, _, rest = name.partition("_")
            areas.setdefault(head if rest else "other", []).append(name)
        lines = [f"{area}: {', '.join(names)}" for area, names in sorted(areas.items())]
        return (
            "Every tool you have. Only the common few are loaded with their "
            "instructions attached; the rest are named here so you know they "
            f"exist. To use one that is not loaded, call {SEARCH_TOOL} with a "
            "word or two and it arrives ready to call. This list is what you "
            "can do -- if something is on it, you can do it, and saying "
            "otherwise is wrong.\n\n" + "\n".join(lines)
        )

    async def _load_found(self, names: list[str]) -> None:
        """Add tools a search just found, for the rest of the session.

        Without this the search is overhead: the model would be told a tool
        exists and still have no way to call it. `update_tools` is on the
        Agent rather than the session, and it is a coroutine -- checked with
        `iscoroutinefunction`, because the annotation on this SDK says `-> None`
        on methods that must be awaited and believing it once already cost a
        release's worth of silently discarded instructions.
        """
        agent = self._agent
        if agent is None:
            return
        fresh = [
            self._as_function_tool(self._catalogue[name])
            for name in names
            if name in self._catalogue and name not in self._loaded
        ]
        if not fresh:
            return
        self._loaded.update(names)
        await agent.update_tools([*agent.tools, *fresh])
        log.info("tool_search: loaded %s", ", ".join(names))
