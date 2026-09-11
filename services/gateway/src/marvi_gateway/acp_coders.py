"""Outside coders -- Claude Code, Codex, OpenCode, Gemini CLI -- over ACP.

`delegate.py` ran `claude -p` or `codex exec` and waited for whatever it
printed. Nothing came back until the end: no progress, no way to say stop that
the agent understood, and every permission decision made up front by a sandbox
flag. The Agent Client Protocol is the one those tools now speak to editors --
JSON-RPC over stdio -- and speaking it gives Marvi what an editor has: the
agent's messages and tool calls as they happen, a plan, a real cancel, and each
permission request asked of Marvi at the moment it matters.

## Same jobs, same screen

An outside coder runs as a `subagents.Job`, so everything already built for
Harvi applies unchanged: `delegated_status`, the voice push, Stop, the desktop
feed with its avatars and live transcript, the stall watcher. Only the engine
differs -- the agent's own loop over ACP instead of Marvi's over her provider.

## Permission, decided the way Marvi decides it

Reads, searches and thinking are allowed. In investigate mode the session is
put in the agent's read-only mode where it has one, and an edit is refused
outright. In fix mode -- already approved once at `delegate_to_coder` -- edits
and commands under the workspace are allowed, exactly as the fix grant allows
Harvi's. Anything else (a network fetch, a mode switch, a kind the protocol
leaves as `other`) becomes an ordinary Marvi confirmation through
`coder_permission`, so the Island, a spoken yes or Telegram answers it, and
YOLO allows it.

## What reaches the agent

The task goes in the prompt over stdin, never in an argument list: the adapters
are `.CMD` shims on Windows and `cmd.exe` would re-parse an argument. The
environment is the SDK's trimmed one -- paths and the user profile, where the
agents keep their own logins -- not the Gateway's, which holds every provider
key Marvi has.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .logs import get_logger

if TYPE_CHECKING:
    from .subagents import Job, Runner

log = get_logger("acp")

#: Pinned adapters, fetched by `npx` on first use when not installed globally.
#: Both Apache-2.0; see `docs/UPSTREAM.md`.
CLAUDE_ACP = "@agentclientprotocol/claude-agent-acp@0.76.0"
CODEX_ACP = "@agentclientprotocol/codex-acp@1.11.0"

#: Long enough for real work, as `delegate.TIMEOUT` was.
TIMEOUT = 1800.0
#: How often the running prompt is checked for Stop and the deadline.
TICK = 0.2

#: Always allowed: looking is not acting.
LOOKING = frozenset({"read", "search", "think"})
#: Refused in investigate mode, allowed under an approved fix job.
CHANGING = frozenset({"edit", "delete", "move"})
#: Allowed under an approved fix job, asked about in investigate.
RUNNING = frozenset({"execute"})

#: Session modes to ask for, by Marvi's mode, in order of preference. Claude
#: Code's adapter offers `plan` and `acceptEdits`; Codex's `read-only` and
#: `auto`. An agent with none of these keeps its default, and the permission
#: rules above still hold.
MODES = {
    "investigate": ("plan", "read-only", "readonly", "read_only", "ask"),
    "fix": ("acceptEdits", "auto", "agent", "default"),
}


@dataclass(frozen=True)
class Coder:
    key: str
    name: str
    description: str
    #: The command that starts its ACP server, or None when it is not installed.
    command: Callable[[], list[str] | None]


def _which(name: str) -> str | None:
    """A program Windows can start, not merely a file with the right name.

    `shutil.which("npx")` answers `C:\\Program Files\\nodejs\\npx` on Python
    3.12 -- the extensionless sh script npm ships beside `npx.cmd` -- and
    starting it fails with WinError 193. The first real run over ACP died of
    exactly that, for both adapters. So the runnable extensions are asked for
    first, as a shell would; a bare name only where there is no PATHEXT.
    """
    if os.name == "nt":
        for extension in (".exe", ".cmd", ".bat"):
            if found := shutil.which(name + extension):
                return found
        return None
    return shutil.which(name)


def _adapter(package: str, needs: str) -> Callable[[], list[str] | None]:
    """A coder reached through an npm ACP adapter, when the coder is installed."""

    def resolve() -> list[str] | None:
        if not _which(needs):
            return None
        binary = package.rsplit("/", 1)[-1].rsplit("@", 1)[0]
        if installed := _which(binary):
            return [installed]
        npx = _which("npx")
        return [npx, "--yes", package] if npx else None

    return resolve


def _native(binary: str, *arguments: str) -> Callable[[], list[str] | None]:
    """A coder that speaks ACP itself."""

    def resolve() -> list[str] | None:
        found = _which(binary)
        return [found, *arguments] if found else None

    return resolve


CODERS: dict[str, Coder] = {
    "claude": Coder(
        "claude",
        "Claude Code",
        "Anthropic's coding agent, over its ACP adapter. Strong on reading an unfamiliar "
        "codebase and explaining what is wrong.",
        _adapter(CLAUDE_ACP, "claude"),
    ),
    "codex": Coder(
        "codex",
        "Codex",
        "OpenAI's coding agent, over its ACP adapter. Strong on making a contained change "
        "and running the tests.",
        _adapter(CODEX_ACP, "codex"),
    ),
    "opencode": Coder(
        "opencode",
        "OpenCode",
        "The open-source coding agent, which speaks ACP itself (`opencode acp`).",
        _native("opencode", "acp"),
    ),
    "gemini": Coder(
        "gemini",
        "Gemini CLI",
        "Google's coding agent, which speaks ACP itself (`gemini --acp`).",
        _native("gemini", "--acp"),
    ),
}


def installed() -> list[Coder]:
    return [coder for coder in CODERS.values() if coder.command()]


def run(runner: Runner, job: Job, coder: Coder, root: Path, prompt: str) -> None:
    """The job thread: one ACP session, start to finish."""
    try:
        asyncio.run(_session(runner, job, coder, root, prompt))
    except Exception as exc:  # the job fails; the Gateway does not
        log.warning("outside coder failed", extra={"marvi_job": job.id, "marvi_error": str(exc)[:240]})
        said = f"{coder.name} stopped on an error: {str(exc)[:300]}"
        # The first real Claude Code run over ACP ended in "401 OAuth access
        # token has been revoked": the agent's own login, not anything Marvi can
        # fix. Said as the one thing to do about it.
        if "authenticat" in str(exc).lower() or " 401" in str(exc):
            said += f" -- {coder.name} needs signing in again on this machine."
        runner._end(job, "failed", "error", said)


class _Client:
    """Marvi's side of the protocol: take the updates, answer permission."""

    def __init__(self, runner: Runner, job: Job, coder: Coder) -> None:
        self.runner, self.job, self.coder = runner, job, coder
        self.chunks: list[str] = []
        self.last_message = ""
        self.steps: dict[str, dict[str, Any]] = {}

    def flush(self) -> None:
        text = "".join(self.chunks).strip()
        self.chunks = []
        if text:
            self.last_message = text
            self.runner._note(self.job, "said", text[:300])

    async def session_update(self, session_id: str, update: Any, **_: Any) -> None:
        self.job.active = time.monotonic()
        kind = getattr(update, "session_update", "")
        if kind == "agent_message_chunk":
            self.chunks.append(str(getattr(update.content, "text", "") or ""))
        elif kind == "tool_call":
            self.flush()
            label = f"{update.kind or 'other'}: {update.title}"[:160]
            event = self.runner._note(self.job, "tool", label, outcome="running")
            self.steps[update.tool_call_id] = event
            self._settle(event, update.status)
        elif kind == "tool_call_update":
            event = self.steps.get(update.tool_call_id)
            if event is not None:
                self._settle(event, update.status)
        elif kind == "plan":
            self.job.todos = [
                {"content": str(entry.content)[:160], "status": str(entry.status)}
                for entry in update.entries[:20]
            ]
            doing = [entry["content"] for entry in self.job.todos if entry["status"] == "in_progress"]
            self.job.progress = doing[0] if doing else ""
            self.runner._publish()

    def _settle(self, event: dict[str, Any], status: str | None) -> None:
        if status in ("completed", "failed"):
            event["outcome"] = "ok" if status == "completed" else "failed"
            self.runner._publish()

    async def request_permission(self, session_id: str, tool_call: Any, options: list[Any], **_: Any) -> Any:
        from acp.schema import AllowedOutcome, DeniedOutcome, RequestPermissionResponse

        allowed = await self._decide(tool_call)
        wanted = ("allow_once", "allow_always") if allowed else ("reject_once", "reject_always")
        chosen = next((option for kind in wanted for option in options if option.kind == kind), None)
        if chosen is None:
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        return RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id=chosen.option_id)
        )

    async def _decide(self, tool_call: Any) -> bool:
        kind = str(getattr(tool_call, "kind", None) or "other")
        title = str(getattr(tool_call, "title", None) or kind)
        fixing = self.job.mode == "fix"
        if kind in LOOKING or (fixing and kind in CHANGING | RUNNING):
            return True
        if not fixing and kind in CHANGING:
            self.runner._note(self.job, "said", f"Refused {kind} ({title[:80]}): this job is read-only.")
            return False
        # Anything else is the owner's, through the one confirmation path. A
        # thread, because the wait is blocking and this loop is reading the
        # agent's stream.
        return await asyncio.to_thread(self.runner.ask_owner, self.job, self.coder.key, kind, title)

    # The agent keeps its own file and terminal tools; Marvi advertises neither
    # capability, so these are never called.
    async def read_text_file(self, *_: Any, **__: Any) -> Any:
        raise NotImplementedError

    async def write_text_file(self, *_: Any, **__: Any) -> Any:
        raise NotImplementedError


async def _session(runner: Runner, job: Job, coder: Coder, root: Path, prompt: str) -> None:
    from acp import PROTOCOL_VERSION, spawn_agent_process, text_block
    from acp.schema import ClientCapabilities, Implementation

    command = coder.command()
    if not command:
        runner._end(job, "failed", "error", f"{coder.name} is not installed")
        return
    client = _Client(runner, job, coder)
    try:
        async with spawn_agent_process(client, command[0], *command[1:], cwd=str(root)) as (conn, _):
            await conn.initialize(
                protocol_version=PROTOCOL_VERSION,
                client_capabilities=ClientCapabilities(),
                client_info=Implementation(name="marvi-os", version="1"),
            )
            session = await conn.new_session(cwd=str(root), mcp_servers=[])
            await _choose_mode(conn, session, job.mode)
            turn = asyncio.create_task(
                conn.prompt(session_id=session.session_id, prompt=[text_block(prompt)])
            )
            deadline = time.monotonic() + TIMEOUT
            asked_to_stop = False
            while not turn.done():
                await asyncio.wait({turn}, timeout=TICK)
                late = time.monotonic() > deadline
                if (job.stop.is_set() or late) and not asked_to_stop:
                    asked_to_stop = True
                    await conn.cancel(session_id=session.session_id)
                    if late:
                        runner._end(job, "failed", "stalled", f"no answer after {int(TIMEOUT // 60)} minutes")
            response = await turn
    except (FileNotFoundError, PermissionError) as exc:
        runner._end(job, "failed", "error", f"{coder.name} could not start: {exc}")
        return
    client.flush()
    said = client.last_message or "It finished without saying anything."
    reason = str(getattr(response, "stop_reason", "") or "")
    if reason == "end_turn":
        runner._end(job, "completed", "completed", said)
    elif reason in ("max_tokens", "max_turn_requests"):
        runner._end(job, "completed", "max_rounds", said)
    elif reason == "cancelled":
        runner._end(job, "interrupted", "stopped", "stopped before it finished")
    else:
        runner._end(job, "failed", "error", said)


async def _choose_mode(conn: Any, session: Any, mode: str) -> None:
    modes = getattr(session, "modes", None)
    offered = {one.id for one in getattr(modes, "available_modes", None) or []}
    wanted = next((one for one in MODES.get(mode, ()) if one in offered), None)
    if wanted and wanted != getattr(modes, "current_mode_id", None):
        await conn.set_session_mode(session_id=session.session_id, mode_id=wanted)
