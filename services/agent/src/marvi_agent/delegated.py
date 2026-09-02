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

#: How often to ask whether a job is done. Slow on purpose: this is work
#: measured in minutes, and the answer reaches the next turn either way.
POLL_EVERY = 15.0

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

    def attach(self, ask: Any) -> None:
        """The callable that asks the Gateway for a job's status."""
        self._ask = ask

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
        while time.monotonic() < deadline:
            time.sleep(POLL_EVERY)
            try:
                result = self._ask(job)
            except Exception as exc:
                log.info("could not check job %s: %s", job, exc)
                continue
            if not isinstance(result, dict) or result.get("state") == "running":
                continue
            with self._lock:
                self._ready.append({"job": job, **result})
                self._watching.discard(job)
            log.info("delegated job %s finished; it will be mentioned next turn", job)
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
        for job in ready:
            said = str(job.get("summary") or job.get("detail") or job.get("state") or "")
            lines.append(f"- job {job['job']}: {said[:MAX_REPORT]}")
        newline = chr(10)
        # Told what to do with it, because the failure otherwise is silence:
        # she reads a finished job, has nothing asking her about it, and says
        # nothing -- which is the same as never having been told.
        return (
            "# Work you handed off has finished" + newline + newline
            + newline.join(lines) + newline + newline
            + "Say this happened, briefly, in your next reply -- even if they "
            "asked about something else, because they are waiting on it. Once "
            "is enough; it is in the conversation after that."
        )


#: One per worker process, which is one conversation.
jobs = Delegated()
