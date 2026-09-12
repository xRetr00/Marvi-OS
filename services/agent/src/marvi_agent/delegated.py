"""Work Marvi handed off, brought back into the conversation on its own.

`delegate_to_coder` starts a job that runs for minutes and returns immediately.
`await_delegated` exists for waiting on one, and it works -- but only if the
model chooses to call it and keeps choosing to wait. When it does not, the job
still finishes and the answer sits in the Gateway until somebody thinks to ask,
which in practice means the owner asking "is that done yet?" about work that
finished four minutes ago.

This is the other half of the talker-reasoner shape LiveKit describes: the fast
model keeps talking while a slower one works, and the result is *pushed* into
the next turn rather than waited for. Marvi already had the talker and the
reasoner. What she did not have was the bridge.

## Why a system message on the next turn

The same seam recall uses. `on_user_turn_completed` is the one place that can
put something in front of the model for exactly one turn without it becoming
part of the persona -- a finished job is news, not a standing fact, and it
should be mentioned once and then live in the transcript like anything else
she said.

## Why it never blocks

Nothing here is awaited by a turn. A poller thread asks the Gateway, and the
turn hook reads whatever has landed. A job that never finishes costs one
background thread and no latency; a Gateway that stops answering costs the
same. The one thing a spoken turn must never do is wait on a coding agent.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger("marvi.voice")

#: How often to ask whether a job is done. It was 15 s, on the reasoning that
#: the answer reaches the next turn either way -- but she now speaks up as soon
#: as it lands, so the poll is most of the delay. A loopback request is cheap.
POLL_EVERY = 3.0

#: How long the owner must have been quiet before she speaks up unprompted.
#: Right after they stop talking their own turn is about to start, and a
#: report dropped into that gap is two replies at once.
QUIET_FOR = 1.5

#: How long to keep asking before giving up on a job. `await_delegated` uses a
#: shorter one because somebody is listening to it; this runs unattended.
GIVE_UP_AFTER = 45 * 60.0

#: How much of a finished job's report to put in front of the model. Enough to
#: say what happened; not the whole diff.
MAX_REPORT = 700


class Delegated:
    """Jobs handed off, and what came back that has not been said yet."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._watching: set[str] = set()
        self._ready: list[dict[str, Any]] = []
        self._ask: Any = None
        self._on_ready: Any = None

    def attach(self, ask: Any) -> None:
        """The callable that asks the Gateway for a job's status."""
        self._ask = ask

    def when_ready(self, callback: Any) -> None:
        """Called, from the poller's thread, whenever something lands.

        The session hands this to its event loop to decide whether Marvi can
        say it now. Without it the report waited for the owner to speak.
        """
        self._on_ready = callback

    def has_news(self) -> bool:
        with self._lock:
            return bool(self._ready)

    def _landed(self) -> None:
        callback = self._on_ready
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:  # a closed loop costs the push, not the poller
            log.info("could not hand a finished job to the session: %s", exc)

    def watch(self, job: str) -> None:
        """Follow a job until it finishes. Safe to call twice for one job."""
        job = str(job or "").strip()
        if not job or self._ask is None:
            return
        with self._lock:
            if job in self._watching:
                return
            self._watching.add(job)
        threading.Thread(
            target=self._follow, args=(job,), daemon=True, name=f"marvi-job-{job}"
        ).start()

    def _follow(self, job: str) -> None:
        deadline = time.monotonic() + GIVE_UP_AFTER
        #: The approval request already said, so the same one is not said
        #: every poll while the owner decides.
        asked = ""
        while time.monotonic() < deadline:
            time.sleep(POLL_EVERY)
            try:
                result = self._ask(job)
            except Exception as exc:
                log.info("could not check job %s: %s", job, exc)
                continue
            if not isinstance(result, dict) or result.get("state") == "running":
                continue
            if result.get("state") == "awaiting_approval":
                # News now, not at the end: a sub-agent waiting on the owner
                # cannot finish until somebody tells them it is asking.
                token = str(result.get("token") or "")
                if token != asked:
                    asked = token
                    with self._lock:
                        self._ready.append({"job": job, **result})
                    self._landed()
                continue
            with self._lock:
                self._ready.append({"job": job, **result})
                self._watching.discard(job)
            log.info("delegated job %s finished; she will say so at the next quiet moment", job)
            self._landed()
            return
        with self._lock:
            self._watching.discard(job)

    def take(self) -> list[dict[str, Any]]:
        """Finished jobs nobody has been told about. Emptied by reading."""
        with self._lock:
            ready, self._ready = self._ready, []
        return ready

    def block(self) -> str:
        """The finished work, as prompt text, or empty when there is none."""
        ready = self.take()
        if not ready:
            return ""
        lines = []
        waiting = False
        for job in ready:
            if job.get("state") == "awaiting_approval":
                waiting = True
                said = str(job.get("detail") or "")
            else:
                said = str(job.get("summary") or job.get("detail") or job.get("state") or "")
            who = f" ({job['name']})" if job.get("name") else ""
            lines.append(f"- job {job['job']}{who}: {said[:MAX_REPORT]}")
        newline = chr(10)
        # Told what to do with it, because the failure otherwise is silence:
        # she reads a finished job, has nothing asking her about it, and says
        # nothing -- which is the same as never having been told.
        told = (
            "Say this happened, briefly, in your next reply -- even if they "
            "asked about something else, because they are waiting on it. Once "
            "is enough; it is in the conversation after that."
        )
        if waiting:
            told += (
                " A job waiting for approval is stuck until the owner answers: say in "
                "plain words exactly what it wants to do and ask them, then pass their "
                "yes or no to delegate_approve. Never answer for them."
            )
        return (
            "# Work you handed off" + newline + newline
            + newline.join(lines) + newline + newline + told
        )


def speak_up(session: Any, delegated: Delegated, quiet_for: float) -> bool:
    """Say finished work now, if nobody is talking. True when she did.

    The owner's report finished at 14:13:42 and was mentioned at 14:13:56 --
    because they happened to say "Prezidon", not because the job was done.
    `session.generate_reply(instructions=...)` is LiveKit's documented way for
    an agent to speak without being spoken to (verified against
    livekit-agents 1.7.0 and docs.livekit.io/agents/build/audio).

    Waits for a genuinely idle moment: Marvi listening with nothing queued,
    the owner not speaking and quiet for `QUIET_FOR` -- just after they stop,
    their own turn is about to begin. When it cannot speak now the report
    stays put, and either the next quiet moment or the owner's next turn
    carries it, so it is never lost and never said twice.
    """
    if getattr(session, "agent_state", "") not in ("listening", "idle"):
        return False
    if getattr(session, "user_state", "") == "speaking" or quiet_for < QUIET_FOR:
        return False
    if getattr(session, "current_speech", None) is not None:
        return False
    block = delegated.block()
    if not block:
        return False
    session.generate_reply(instructions=block)
    return True


#: One per worker process, which is one conversation.
jobs = Delegated()
