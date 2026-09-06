"""Noticing that nobody is talking any more, and leaving.

A voice session ended when the model decided to call `end_conversation`, when
the user closed it, or never. "Never" turned out to be the common case: two
sessions in one day ran to **305 minutes** and **137 minutes** with the
microphone open, answering whatever was said in an empty room.

    13:44:30 -> 18:49:19   305 min
    21:29:08 -> 23:45:41   137 min

The wake word is not the cause. It runs in its own host process and its only
job is to launch the app; it fired once that day, at 22:22, well inside a
session that had already been open for an hour. Every rule about when to speak
was working exactly as written. The session simply had no end, so it did not
have one.

## Two different silences

Somebody sitting thinking is quiet. Somebody who left the house is also quiet,
and the two want very different amounts of patience: interrupting the first is
rude and staying for the second is what "talking to air" means.

The room already knows which it is -- `presence` fuses mmWave, the camera,
OwnTracks and Bluetooth -- so this asks, and waits ten minutes for a person who
is there and two for a room that is empty.

## Why it says goodbye

Leaving silently is indistinguishable from crashing. One short line costs
nothing and is the difference between an assistant that finished and one that
died.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

log = logging.getLogger("marvi.voice")

#: Nobody has said anything for this long, and somebody is there.
#:
#: Long enough to think, read something, or take a call on another phone.
#: A person who is present and quiet has not finished talking to you.
QUIET_AND_PRESENT = 10 * 60.0

#: And this long when the room says nobody is in it.
#:
#: Short, because there is nothing to interrupt. Not instant, because presence
#: fails open and a sensor blinking off for thirty seconds is not somebody
#: leaving.
QUIET_AND_ALONE = 2 * 60.0

#: How often the question gets asked. Cheap: a comparison against a timestamp,
#: plus one Gateway call only once the shorter of the two has already passed.
LOOK_EVERY = 20.0


class Alone:
    """Tracks when anybody last spoke, and ends a call that has gone quiet.

    Held by the session and told about every turn. `heard()` from the recogniser
    and `spoke()` from the reply, because either one means the call is alive --
    a long answer she is still delivering is not an idle call.
    """

    def __init__(self, *, present: Any = None, farewell: Any = None) -> None:
        #: `() -> bool | None` -- whether anybody is there, None when unknown.
        self.present = present
        #: `(line) -> Awaitable` -- says one short goodbye before leaving.
        self.farewell = farewell
        self._last = time.monotonic()
        self._ended = False

    def heard(self) -> None:
        self._last = time.monotonic()

    def spoke(self) -> None:
        self._last = time.monotonic()

    @property
    def quiet_for(self) -> float:
        return time.monotonic() - self._last

    def _somebody_there(self) -> bool | None:
        if self.present is None:
            return None
        try:
            return self.present()
        except Exception as exc:
            # Unknown, not absent. Ending a call because a sensor failed is the
            # same failure this module exists to prevent, in the other
            # direction.
            log.info("could not tell whether anybody is here (%s); assuming they are", str(exc)[:120])
            return None

    def should_leave(self, there: bool | None) -> str:
        """Why she should end the call now, or empty to stay.

        Takes presence rather than fetching it, so the decision is a pure
        function of two numbers and a tri-state -- testable without a Gateway,
        and with no way for an HTTP call to end up on the audio loop.
        """
        quiet = self.quiet_for
        if quiet < QUIET_AND_ALONE:
            return ""
        if there is False:
            return "the room is empty"
        if quiet >= QUIET_AND_PRESENT:
            return "nobody has said anything"
        return ""

    async def watch(self, leave: Any) -> None:
        """Ask every `LOOK_EVERY` seconds, and call `leave(why)` once.

        Never raises out: a watchdog that kills the session it is watching is
        worse than one that stops watching.
        """
        while not self._ended:
            await asyncio.sleep(LOOK_EVERY)
            try:
                # Asked only once the shorter patience has already run out, and
                # on a thread: `present` reaches the Gateway over HTTP, and this
                # coroutine shares a loop with the audio.
                there = (
                    await asyncio.to_thread(self._somebody_there)
                    if self.quiet_for >= QUIET_AND_ALONE
                    else None
                )
                why = self.should_leave(there)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("idle check failed (%s); the call stays open", str(exc)[:160])
                continue
            if not why:
                continue
            self._ended = True
            log.info(
                "ending the call: %s for %.0f minutes", why, self.quiet_for / 60,
                extra={"marvi_reason": why, "marvi_quiet_minutes": round(self.quiet_for / 60)},
            )
            try:
                await leave(why)
            except Exception as exc:  # pragma: no cover - depends on the session
                log.warning("could not end the idle call cleanly: %s", str(exc)[:160])
            return


#: What she says on the way out. Short, and different for the two silences:
#: "I will leave you to it" is wrong said to an empty room, and "I will head
#: off" is wrong said to somebody sitting right there.
def farewell_for(why: str) -> str:
    if why == "the room is empty":
        return ""
    return "I will leave you to it. Say my name when you need me."
