"""Noticing that a source has stopped talking, and saying so.

Every feeder Marvi has fails the same way: not with an error, but by going
quiet. Nothing raises, nothing turns red, and the last reading simply stands
there looking current forever. That is the worst failure shape available to a
system built on sensors, because it is indistinguishable from good news.

It happened for thirteen days. OwnTracks stopped publishing because Tailscale
had gone offline on the phone, so the phone could not reach the broker -- and
Marvi went on reporting `home: true` from a geofence event dated the 24th of
August, on a page that said "Phone: HOME" in confident capitals. Nobody was
lying. Nobody had checked.

## Silence is not an error, so it needs a clock

There is no event to react to here, which is the whole difficulty: this fires
on the *absence* of events. So each feed carries how long it may reasonably go
quiet -- a phone that reports on movement may be still for hours, a camera
should never be quiet for a minute -- and going past that is the news.

## Said once, and again only if it gets worse

A feed that has been down since Tuesday is not new information on Thursday.
The first crossing is worth interrupting for; after that it belongs on a page.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .logs import get_logger

log = get_logger("mind")


@dataclass(frozen=True)
class Feed:
    """One source, and how long its silence means nothing."""

    #: The key in the room state, or a well-known name.
    id: str
    #: What to call it out loud.
    label: str
    #: Longer than this without a word is worth saying.
    quiet_seconds: float
    #: What it usually means, when it is the likeliest cause.
    hint: str = ""


#: Deliberately generous. A false "your phone has stopped reporting" is worse
#: than a slow true one -- it teaches you to ignore the warning.
FEEDS: tuple[Feed, ...] = (
    Feed(
        "phone",
        "your phone",
        6 * 3600.0,
        # The real cause, the one time this mattered: OwnTracks reaches the
        # broker over Tailscale, and Tailscale had quietly gone offline.
        "OwnTracks may have lost its connection -- check Tailscale and the app",
    ),
    Feed("camera", "the camera", 15 * 60.0, "the vision worker may have stopped"),
    Feed("mmwave", "the presence sensor", 30 * 60.0, "the mmWave sensor may be offline"),
    Feed("bluetooth", "the room's Bluetooth", 60 * 60.0, "ESPresense may be offline"),
)

BY_ID = {feed.id: feed for feed in FEEDS}


@dataclass
class Quiet:
    """A feed that has stopped talking."""

    feed: Feed
    silent_for: float

    def sentence(self, name: str = "") -> str:
        who = f"{name}, " if name else ""
        hours = self.silent_for / 3600.0
        how_long = (
            f"{self.silent_for / 60:.0f} minutes" if hours < 1
            else f"{hours:.0f} hours" if hours < 48
            else f"{hours / 24:.0f} days"
        )
        line = f"{who}I have not heard from {self.feed.label} in {how_long}."
        # The hint is most of the value. "Your phone has stopped reporting" is
        # a fact; "check Tailscale" is something a person can act on.
        return f"{line} {self.feed.hint}." if self.feed.hint else line


class Watcher:
    """Notices feeds going quiet, and says so once each."""

    def __init__(self) -> None:
        #: Feed id -> the silence already reported, so it is not repeated
        #: until it is meaningfully worse.
        self._told: dict[str, float] = {}

    def look(self, ages: dict[str, float | None], now: float | None = None) -> list[Quiet]:
        """Which feeds have newly gone quiet. `ages` is seconds since each spoke.

        `None` means "never heard from", which is not the same as "stopped" --
        a camera that was never configured has not gone quiet, it was never
        there, and warning about it every hour would be noise about a choice.
        """
        del now
        found: list[Quiet] = []
        for key, age in ages.items():
            feed = BY_ID.get(key)
            if feed is None or age is None:
                continue
            if age < feed.quiet_seconds:
                # Talking again. Forget it, so the next outage is news.
                if self._told.pop(key, None) is not None:
                    log.info("%s is reporting again", feed.label)
                continue
            told = self._told.get(key)
            # Twice as long is worth mentioning again; an hour more is not.
            if told is not None and age < told * 2:
                continue
            self._told[key] = age
            found.append(Quiet(feed, age))
            log.warning(
                "%s has been quiet for %.0f minutes", feed.label, age / 60,
                extra={"marvi_feed": key, "marvi_quiet_seconds": round(age)},
            )
        return found

    def forget(self) -> None:
        self._told.clear()


def ages_from(signals: list[Any]) -> dict[str, float | None]:
    """Seconds since each presence signal last spoke.

    Reuses `presence.signals`, which has already normalised four differently
    shaped blobs and -- since the ISO fix -- actually measures their ages. This
    is the same data the room reads; the only new thing is looking at *how old*
    rather than at what it says.
    """
    return {signal.source: signal.age for signal in signals}
