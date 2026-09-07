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

## Why not a list of app names

Because that was the first attempt and it was wrong in the way that matters.
`steam`, `epicgames` and `battle.net` were on it, and those are *stores*: they
sit in the tray from login to shutdown using no GPU at all. Marvi would have
stood down off the card permanently, on a machine where no game was running,
and the only symptom would have been that she never prewarmed again.

The name was never the question. "Is something using the card" is the
question, and Windows answers it directly:

* `SHQueryUserNotificationState` says whether a fullscreen app is in the
  foreground -- 2 (`QUNS_BUSY`) or 3 (`QUNS_RUNNING_D3D_FULL_SCREEN`). Epic in
  the tray is neither. It needs polling, because Windows sends no notification
  when a fullscreen app starts or stops, and polling is what this already does.
* `nvidia-smi` says what percentage of the GPU is actually in use.

Both together: a fullscreen window *and* real load on the card. A launcher
fails the first test, an idle desktop fails both, and a game nobody has ever
heard of passes both -- which a list could never do.

The names survive only as labels, so she can say "FC 26" instead of "FC26.exe",
and as a fallback on a machine with no NVIDIA telemetry to read.
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
    "fc26", "fc25", "fifa", "leagueoflegends", "valorant", "csgo", "cs2",
    "dota2", "gta", "rdr2", "cyberpunk", "eldenring", "minecraft", "roblox",
    "fortnite", "apex", "warzone", "callofduty", "pubg", "rocketleague",
    "forza", "assassin",
    # Not games, and they want the card just as much.
    "blender", "davinci", "premiere", "aftereffects", "handbrake",
    "unrealeditor", "unity",
)

#: Deliberately absent: steam, epicgames, battle.net, riotclient.
#:
#: They were on the list and they are the bug. A store sits in the tray from
#: login to shutdown using no GPU, so matching on its name meant standing down
#: off the card forever on a machine where nothing was being played -- and the
#: only symptom would have been Marvi never prewarming again.

#: Fullscreen states from `SHQueryUserNotificationState`: a fullscreen app is
#: in the foreground (2) or a Direct3D one specifically (3).
FULLSCREEN_STATES = (2, 3)

#: How much of the GPU counts as "in use by something else". A game pegs the
#: card; a fullscreen video sits far below this; a desktop idles near zero.
#: Measured here at 11% with nothing running.
GPU_BUSY_PERCENT = 40.0

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


def fullscreen_now() -> bool:
    """Whether a fullscreen app has the foreground, as Windows sees it.

    False on anything that is not Windows, and False when the call fails --
    the safe direction, because the consequence of a false positive here is
    Marvi standing down off the GPU when nothing needs it.
    """
    try:
        import ctypes

        state = ctypes.c_int()
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
        return state.value in FULLSCREEN_STATES
    except Exception:
        return False


def gpu_in_use() -> float | None:
    """Percent of the GPU in use, or None when nothing can say.

    `nvidia-smi` is a subprocess, so this is only called once a fullscreen app
    has already been seen -- a few times an hour rather than every minute.
    """
    import subprocess

    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8, check=True,
        ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        try:
            return float(line.strip())
        except ValueError:
            continue
    return None


def named_heavy(window: dict[str, Any] | None) -> str:
    """Whether this window's name is on the list. A label, not a decision."""
    if not window:
        return ""
    app = _name_of(window)
    haystack = f"{app} {window.get('title', '')}".lower().replace(" ", "")
    for needle in HEAVY_APPS + extra_apps():
        if needle in haystack:
            return app or needle
    return ""


def is_heavy(window: dict[str, Any] | None) -> str:
    """The name of the thing that has the machine, or empty.

    Fullscreen *and* real load on the card. Either alone is not enough: a
    launcher in the tray is neither, a fullscreen video is the first without
    the second, and a compile is the second without the first -- and none of
    those is a reason to stop being able to speak.
    """
    if not window or not fullscreen_now():
        return ""
    app = _name_of(window)
    busy = gpu_in_use()
    if busy is None:
        # No telemetry to read. Fall back to the name, which is all the older
        # version ever had -- but only for something already fullscreen.
        return named_heavy(window)
    if busy < GPU_BUSY_PERCENT:
        return ""
    return app or named_heavy(window) or "something"


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
        # Already standing down: the only question left is whether the
        # fullscreen app has gone, and that is a ctypes call costing nothing.
        #
        # `nvidia-smi` is a process spawn that takes a driver lock -- measured
        # here at 46-118ms -- and asking it every minute for the whole length
        # of a match is sixty driver stalls an hour inside the game it exists
        # to protect.
        if self._heavy and fullscreen_now():
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
