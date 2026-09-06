"""What the person is actually doing, and getting out of the way when it matters.

`ActivityWatch` has known the focused window since it was added, and nothing
used it for anything except answering a question if asked. So Marvi could tell
you what app was open and never *did* anything about it -- which is the whole
difference between a machine that reports and one that notices.

Two things come out of that.

**Getting out of the way.** A game wants the GPU, all of it, and Marvi's
speech models sit on the same card. Prewarming a TTS model in the middle of a
match costs frames and adds heat for no benefit, because nobody is talking to
her anyway. The agent already knows how to wait rather than take the card --
`oncall.wait_until_free` does exactly that for a live call -- so this gives it
a second reason to wait.

**Saying so, once, warmly.** The point is not a notification. It is that
handing over the GPU without a word is indistinguishable from doing nothing,
and a line as it happens is what makes the difference legible:

    Hey Shereef, I've put myself in low-resource mode so you can enjoy FC26.
    Go beat some asses.

## Why a list rather than a detector

Detecting "is this a game" properly means per-process GPU counters, which on
Windows means either a driver API or WMI, and both cost more than the answer is
worth on a five-minute timer. A name list is embarrassing and it works: the set
of things somebody plays is small, changes rarely, and the person can add to it
without a release. `MARVI_HEAVY_APPS` extends it.

Being wrong is cheap in both directions. A false positive means Marvi does not
prewarm for a few minutes and says something friendly. A false negative means
today's behaviour.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from typing import Any

from .logs import get_logger

log = get_logger("mind")

#: Things that want the whole machine. Matched against the executable name and
#: the window title, case-insensitively, as substrings -- `fc2` would match
#: half of Steam, so these are deliberately whole-ish words.
HEAVY_APPS: tuple[str, ...] = (
    # Named first because it is the one actually played here.
    "fc26", "fc25", "fifa",
    "steam", "epicgames", "battle.net", "riotclient", "leagueoflegends",
    "valorant", "csgo", "cs2", "dota2", "gta", "rdr2", "cyberpunk",
    "eldenring", "minecraft", "roblox", "fortnite", "apex", "warzone",
    "callofduty", "pubg", "rocketleague", "forza", "assassin",
    # Not games, and they want the card just as much.
    "blender", "davinci", "premiere", "aftereffects", "obs64", "handbrake",
    "unrealeditor", "unity",
)

#: Extra names from the environment, comma separated. The list above cannot
#: know what somebody installed yesterday.
SETTING = "MARVI_HEAVY_APPS"

#: A window has to hold still this long before it counts as "what they are
#: doing". Alt-tabbing through a launcher should not flip the machine into
#: low-resource mode and back with an announcement each way.
SETTLED_LOOKS = 2


def extra_apps() -> tuple[str, ...]:
    raw = os.environ.get(SETTING, "")
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


def _name_of(window: dict[str, Any] | None) -> str:
    if not window:
        return ""
    app = str(window.get("app") or "").strip()
    return re.sub(r"\.exe$", "", app, flags=re.IGNORECASE)


def is_heavy(window: dict[str, Any] | None) -> str:
    """The name of the demanding thing in this window, or empty.

    Checks the executable and the title, because a launcher often runs the game
    as a child process and keeps its own name in the window.
    """
    if not window:
        return ""
    app = _name_of(window)
    haystack = f"{app} {window.get('title', '')}".lower().replace(" ", "")
    for needle in HEAVY_APPS + extra_apps():
        if needle in haystack:
            return app or needle
    return ""


#: A friendlier name than the executable, where the difference matters.
PRETTY: dict[str, str] = {
    "fc26": "FC 26", "fc25": "FC 25", "cs2": "Counter-Strike",
    "csgo": "Counter-Strike", "dota2": "Dota", "rdr2": "Red Dead",
    "obs64": "OBS", "unrealeditor": "Unreal", "davinci": "DaVinci Resolve",
    "aftereffects": "After Effects", "eldenring": "Elden Ring",
    "leagueoflegends": "League", "rocketleague": "Rocket League",
}


def pretty(app: str) -> str:
    key = app.lower().replace(" ", "")
    if key in PRETTY:
        return PRETTY[key]
    # `FC26.exe` -> `FC26`; `Code.exe` -> `Code`. Left alone otherwise, because
    # guessing at capitalisation is how you get "Discord" as "DISCORD".
    return app


@dataclass
class Change:
    """Something about what they are doing that just changed."""

    kind: str
    summary: str
    payload: dict[str, Any]


class Focus:
    """Watches the foreground app and holds the resource mode.

    Read by two callers on two threads -- the scheduler that looks, and the
    request that answers "may I use the GPU" -- so the mode is behind a lock
    and is a plain bool that anybody can read cheaply.
    """

    def __init__(self, activity: Any = None) -> None:
        self.activity = activity
        self._lock = threading.Lock()
        self._heavy: str = ""
        self._candidate: str = ""
        self._looks: int = 0

    # -- what everything else asks -------------------------------------------

    @property
    def low_resource(self) -> bool:
        """Whether something else should have the GPU right now."""
        with self._lock:
            return bool(self._heavy)

    @property
    def because(self) -> str:
        with self._lock:
            return pretty(self._heavy) if self._heavy else ""

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            heavy = self._heavy
        return {
            "low_resource": bool(heavy),
            "because": pretty(heavy) if heavy else "",
            "app": heavy,
        }

    # -- the scheduled look --------------------------------------------------

    def look(self) -> list[Change]:
        """Notice a demanding app arriving or leaving. Empty most of the time."""
        if self.activity is None:
            return []
        try:
            window = self.activity.current_window()
        except Exception as exc:
            log.info("focus: could not read the focused window (%s)", str(exc)[:120])
            return []

        found = is_heavy(window)
        # Held still for two looks before acting. Alt-tabbing out of a game for
        # ten seconds is not the end of the session, and announcing both ways
        # each time somebody checks Discord would be unbearable.
        if found != self._candidate:
            self._candidate, self._looks = found, 1
            return []
        self._looks += 1
        if self._looks < SETTLED_LOOKS:
            return []

        with self._lock:
            was, self._heavy = self._heavy, found
        if found == was:
            return []
        if found:
            log.info(
                "focus: %s is running; standing down to low-resource mode", found,
                extra={"marvi_app": found},
            )
            return [Change("heavy_app_started", f"{pretty(found)} started",
                           {"app": found, "name": pretty(found)})]
        log.info("focus: %s closed; back to normal", was, extra={"marvi_app": was})
        return [Change("heavy_app_ended", f"{pretty(was)} finished",
                       {"app": was, "name": pretty(was)})]
