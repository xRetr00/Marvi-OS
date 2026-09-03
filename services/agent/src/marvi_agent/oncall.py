"""Whether a call is happening, readable from a process that is not in it.

The warm pool is what makes a join feel like a phone call: LiveKit keeps one
idle process with the models already resident, hands it to the job, and starts
a replacement. The replacement runs `prewarm`, which loads Kyutai-1B and the
TTS onto the same GPU the live call is using -- and it starts the moment the
job is taken, which is to say the moment somebody begins talking.

From the log of one call:

    13:51:37.6  job starts, process already warm
    13:51:38.1  joined, listening
    13:51:40.0  the user starts speaking
    13:51:45.9  stt: kyutai ready in 8.2s          <- the replacement, mid-call
    13:51:47.5  job runner initialized

Measured on this card, a second checkpoint loading while a call runs costs the
recogniser about a fifth of its speed -- 157 ms to 187 ms per flush, worst
203 ms -- and it puts a second 2.3 GB model on a 12 GB card for no reason at
all, because nobody is joining a second call while the first is running.

So the replacement waits. It cannot see the job process's memory, and the
Gateway is a poor thing to make the GPU path depend on, so the signal is a
file the live job keeps fresh. Freshness rather than existence: a job that
crashes stops writing, and the pool is refilling again seconds later instead
of waiting for a call that is already over.

The cost of this is that a *second* join during a call lands on a cold
process. That is what already happens whenever the pool is empty, it is one
person's assistant, and the alternative is robbing the call that is actually
happening.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time

from .parakeet_stt import APP_DATA

log = logging.getLogger("marvi.voice")

#: Touched by the live job, read by anything about to take the GPU.
MARKER = APP_DATA / "state" / "voice-call.live"

#: How often the live job says it is still here.
BEAT = 3.0

#: How old the mark may be before the call is assumed over. Three beats, so an
#: ordinary scheduling hiccup is not mistaken for a dead job.
STALE = 10.0

#: The longest a prewarm will wait. Staleness already handles a crash; this is
#: for the case where something keeps the mark fresh forever.
PATIENCE = 600.0

#: How long the worker must allow a process to finish initialising.
#:
#: Not a free number: the wait happens *inside* `prewarm`, which LiveKit runs
#: under `initialize_process_timeout`, so waiting for a call spends the
#: process's initialisation budget. At 180 seconds -- chosen when the only
#: thing in there was loading models -- a call longer than three minutes killed
#: the spare outright:
#:
#:     15:03:02.44  prewarm: a call is in progress; waiting
#:     15:05:53.57  prewarm: the call ended after 171.1s; loading the models now
#:     15:06:02.50  error initializing process ... TimeoutError   <- 180.06s
#:     15:06:04.64  prewarm total 11.1s          <- the load that had just begun
#:     15:06:17.71  prewarm total 13.0s          <- and its replacement, again
#:
#: The wait had used 171 of the 180, the load needed 11 more, and the process
#: was killed two seconds from being ready -- so the card loaded Kyutai twice
#: more, back to back, immediately after the call.
#:
#: Derived from `PATIENCE` rather than written next to it, because the failure
#: is what happens when the two drift apart. The margin is five minutes over
#: the longest wait: the slowest prewarm ever measured here is 48.6 s.
INIT_BUDGET = PATIENCE + 300.0


def busy() -> bool:
    """Is a call happening right now, as far as anyone can tell from here."""
    try:
        return time.time() - MARKER.stat().st_mtime < STALE
    except OSError:
        # Missing is the common case and means no call. Unreadable is treated
        # the same way: refusing to prewarm because a file could not be
        # stat-ed would break joins to protect a call that may not exist.
        return False


class Marker:
    """Keeps the mark fresh for as long as the call lasts."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        MARKER.parent.mkdir(parents=True, exist_ok=True)
        self._touch()
        self._thread = threading.Thread(target=self._beat, name="oncall", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Removed rather than left to go stale, so the replacement can start
        # loading the moment the call ends instead of ten seconds later.
        with contextlib.suppress(OSError):
            MARKER.unlink()

    def _touch(self) -> None:
        with contextlib.suppress(OSError):
            MARKER.write_text(str(os.getpid()), encoding="utf-8")

    def _beat(self) -> None:
        while not self._stop.wait(BEAT):
            self._touch()


def wait_until_free(patience: float = PATIENCE) -> float:
    """Block while a call is running. Returns how long that took.

    Called from `prewarm`, on a worker process that has just been created to
    replace one a job took. There is nothing to lose by waiting: this process
    has no job and the only thing it would do with the GPU is take it from the
    call that does.
    """
    if not busy():
        return 0.0
    began = time.monotonic()
    log.info("prewarm: a call is in progress; waiting rather than taking the GPU from it")
    while busy() and time.monotonic() - began < patience:
        time.sleep(0.5)
    waited = time.monotonic() - began
    if waited >= patience:
        log.warning(
            "prewarm: waited %.0fs for a call to finish and gave up; loading anyway. "
            "The marker at %s may be stale.",
            waited,
            MARKER,
        )
    else:
        log.info("prewarm: the call ended after %.1fs; loading the models now", waited)
    return waited
