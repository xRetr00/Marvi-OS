"""Noticing that the Gateway is struggling, without being told where to look.

`condition.doing` needs somebody to have decided, in advance, that a
particular operation was worth naming. That is the wrong shape for the problem
it was written for: nobody predicted that the *embedding model* would be the
thing that blocked the loop for ten seconds, which is exactly why it took days
of "Gateway unavailable" to find. Wrapping suspects one at a time only ever
catches the ones already under suspicion.

So this watches generically, and there are only two things worth watching.

**Every request, timed.** One middleware, no annotations, no guessing in
advance which endpoint will be the slow one. Whatever drags, drags with a path
attached.

**The event loop itself.** A request that is slow because it is waiting on a
provider is ordinary and affects one caller. A request that is slow because
something is running CPU-bound work *on the loop* stops everything, including
the health poll the desktop turns into "Gateway unavailable". Those two are
indistinguishable to a request timer and completely different to the person
looking at the status bar, so the loop is measured on its own: sleep a known
interval, and whatever the sleep took beyond it is time the loop could not run
anything.

That second measurement is what would have found the embedding load on the
first day, from outside, without anyone having guessed where to look.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from . import condition
from .logs import get_logger

log = get_logger("gateway")

#: How often the loop is asked whether it is still responsive.
HEARTBEAT = 1.0

#: Lag past this means something is running on the loop that should not be.
#:
#: A healthy loop wakes within a few milliseconds of its timer. A quarter of a
#: second is well past scheduling noise and well below the two seconds at which
#: the desktop gives up on a request and calls the Gateway unavailable -- so
#: this fires while there is still something useful to say.
BLOCKED = 0.25

#: Requests slower than this are worth a line. Not so low that ordinary
#: provider calls -- slow because the internet is -- fill the log; those are
#: already timed by `providers`.
SLOW_REQUEST = 2.0


async def watch_the_loop(stopping: asyncio.Event) -> None:
    """Report whenever the event loop was blocked, and for how long."""
    while not stopping.is_set():
        began = time.monotonic()
        try:
            await asyncio.wait_for(stopping.wait(), timeout=HEARTBEAT)
            return
        except TimeoutError:
            pass
        lag = time.monotonic() - began - HEARTBEAT
        if lag >= BLOCKED:
            # What it was doing, when anything said. Without that this still
            # reports the fact, which is most of the value: "unavailable"
            # becomes "blocked for 9.8 seconds".
            busy = condition.now()
            log.warning(
                "the event loop was blocked for %.1fs%s; anything asking during "
                "that time got no answer",
                lag,
                f" while {busy}" if busy else "",
                extra={"marvi_lag_seconds": round(lag, 2), "marvi_doing": busy},
            )
            condition.note(busy or "busy with something on the main loop", lag, regardless=True)


def slow_requests(app: Any) -> None:
    """Time every request, and say which ones dragged or failed.

    Middleware rather than a decorator on each endpoint: the endpoint that
    turns out to be slow is never the one anybody thought to annotate.
    """

    @app.middleware("http")
    async def _timed(request: Any, call_next: Callable[[Any], Awaitable[Any]]) -> Any:
        began = time.monotonic()
        path = getattr(getattr(request, "url", None), "path", "?")
        try:
            response = await call_next(request)
        except Exception as exc:
            spent = time.monotonic() - began
            log.warning(
                "%s failed after %.1fs: %s",
                path,
                spent,
                exc,
                extra={"marvi_path": path, "marvi_seconds": round(spent, 2)},
            )
            condition.note(f"answering {path}", spent, failed=str(exc)[:200])
            raise
        spent = time.monotonic() - began
        if spent >= SLOW_REQUEST:
            log.warning(
                "%s took %.1fs to answer",
                path,
                spent,
                extra={"marvi_path": path, "marvi_seconds": round(spent, 2)},
            )
            condition.note(f"answering {path}", spent)
        return response
