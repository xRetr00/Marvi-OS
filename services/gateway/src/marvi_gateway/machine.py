"""The machine's own condition, as something Marvi notices.

Every feeder Marvi had watched the world *through* the machine -- the room's
camera, a mailbox, a calendar, the focused window -- and none of them watched
the machine itself. So the one thing she is actually running on was the one
thing she could not tell you about, and "your computer finally has a mind" was
true of everything except the computer.

This is the cheapest possible fix for that and deliberately so. No model, no
network, no credentials: `psutil` and `shutil` answer all of it in a few
milliseconds, which matters because it runs on a timer forever. It also means
these events are *trusted* in the sense `policy` uses -- nobody else wrote
them, so unlike a mail subject there is nothing here that a stranger chose.

## Only on the way across

A disk that has been full for a week is not news every two minutes. Each
watcher reports when a threshold is *crossed*, and rearms only once the
reading has recovered past a margin, so a value hovering on the line does not
produce a stream of alternating events. `mind` has repetition handling of its
own; this exists so that machinery never has to see the repeats at all.
"""

from __future__ import annotations

import json
import shutil
import socket
from dataclasses import dataclass, field
from typing import Any

from .logs import get_logger

log = get_logger("mind")

#: Free space below this is worth mentioning, and below the second is worth
#: interrupting for. Absolute rather than a percentage: 5% of a 4TB disk is
#: 200GB and fine, 5% of a 256GB laptop disk is not, and what actually matters
#: is whether the next thing you do will fail.
DISK_LOW_GB = 20.0
DISK_CRITICAL_GB = 5.0

#: How far a reading must recover before the same warning may fire again.
#: Without it, a disk sitting exactly on the threshold alternates forever.
RECOVERY_MARGIN_GB = 3.0

#: Battery percentages. Below the first is a warning, below the second is
#: "save your work".
BATTERY_LOW = 25
BATTERY_CRITICAL = 10

#: Memory in use above this is worth a word -- usually it means something has
#: run away rather than that the machine is small.
MEMORY_TIGHT_PERCENT = 92.0


@dataclass
class Reading:
    """One thing worth saying about the machine right now."""

    kind: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)


def _drives() -> list[str]:
    """Fixed drives worth watching, cheaply and without a dependency.

    Windows lettered drives that answer `disk_usage`. A network drive that has
    gone away raises, which is the correct thing to skip rather than report --
    a disconnected share is not a disk filling up.
    """
    import string

    found = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:/"
        try:
            shutil.disk_usage(root)
        except OSError:
            continue
        found.append(root)
    return found


class Machine:
    """Watches the machine and reports only what changed.

    Holds the last state so a threshold crossing is an event and a threshold
    that has already been crossed is silence.
    """

    def __init__(self, path: Any = None) -> None:
        #: Where what has already been said is kept between runs.
        #:
        #: In memory alone this re-announced every standing condition on every
        #: restart, and the Gateway restarts often -- eighteen times in two
        #: days. "D: has 16GB free" was said seven times, each one exactly five
        #: minutes after a start, because a fresh watcher has never reported
        #: anything and a full disk is still full.
        self.path = path
        #: Drive root -> the worst level already reported ("low"/"critical").
        self._disk: dict[str, str] = {}
        self._battery: str = ""
        self._plugged: bool | None = None
        self._memory: bool = False
        self._online: bool | None = None
        self._load()

    # -- what has already been said ------------------------------------------

    def _load(self) -> None:
        if self.path is None:
            return
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(saved, dict):
            return
        self._disk = {str(k): str(v) for k, v in (saved.get("disk") or {}).items()}
        self._battery = str(saved.get("battery") or "")
        self._memory = bool(saved.get("memory"))
        # `plugged` and `online` are deliberately not restored. Both report on
        # *change*, and the change that matters across a restart is one nobody
        # saw -- announcing "back online" because the last run remembered being
        # offline would be reporting the restart, not the network.

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(
                    {"disk": self._disk, "battery": self._battery, "memory": self._memory}
                ),
                encoding="utf-8",
            )
        except Exception as exc:  # pragma: no cover - disk
            log.info("could not remember what the machine already reported: %s", str(exc)[:120])

    # -- the individual watchers ---------------------------------------------

    def _look_at_disks(self) -> list[Reading]:
        seen: list[Reading] = []
        for root in _drives():
            try:
                free = shutil.disk_usage(root).free / 1e9
            except OSError:
                continue
            was = self._disk.get(root, "")
            if free <= DISK_CRITICAL_GB:
                level = "critical"
            elif free <= DISK_LOW_GB:
                level = "low"
            elif free >= DISK_LOW_GB + RECOVERY_MARGIN_GB:
                # Recovered with room to spare: the warning may fire again.
                level = ""
            else:
                # In the margin. Hold whatever was last reported rather than
                # clearing, so a disk hovering on the line stays quiet.
                level = was
            if level and level != was:
                seen.append(
                    Reading(
                        f"disk_{level}",
                        f"{root[0]}: has {free:.0f}GB free",
                        {"drive": root[0], "free_gb": round(free, 1), "level": level},
                    )
                )
            self._disk[root] = level
        return seen

    def _look_at_power(self) -> list[Reading]:
        try:
            import psutil

            battery = psutil.sensors_battery()
        except Exception:
            return []
        if battery is None:
            # A desktop. Not a failure, just nothing to say, ever.
            return []
        seen: list[Reading] = []
        percent = int(battery.percent)
        plugged = bool(battery.power_plugged)
        level = (
            "critical" if percent <= BATTERY_CRITICAL
            else "low" if percent <= BATTERY_LOW
            else ""
        )
        if plugged:
            level = ""
        if level and level != self._battery:
            seen.append(
                Reading(
                    f"battery_{level}",
                    f"battery at {percent}%",
                    {"percent": percent, "level": level},
                )
            )
        self._battery = level
        if self._plugged is not None and plugged != self._plugged:
            seen.append(
                Reading(
                    "power_plugged" if plugged else "power_unplugged",
                    "plugged in" if plugged else f"running on battery, {percent}%",
                    {"percent": percent, "plugged": plugged},
                )
            )
        self._plugged = plugged
        return seen

    def _look_at_memory(self) -> list[Reading]:
        try:
            import psutil

            used = psutil.virtual_memory().percent
        except Exception:
            return []
        tight = used >= MEMORY_TIGHT_PERCENT
        seen = []
        if tight and not self._memory:
            seen.append(
                Reading("memory_tight", f"memory at {used:.0f}%", {"percent": round(used, 1)})
            )
        self._memory = tight
        return seen

    def _look_at_network(self) -> list[Reading]:
        """Whether this machine can reach anything.

        A DNS lookup rather than a ping: it is what actually breaks first and
        what everything else depends on. Half a second at most, and only on the
        way across -- a machine that has been offline for an hour says nothing.
        """
        try:
            socket.setdefaulttimeout(1.5)
            socket.getaddrinfo("cloudflare.com", 443)
            online = True
        except Exception:
            online = False
        seen = []
        if self._online is not None and online != self._online:
            seen.append(
                Reading(
                    "network_back" if online else "network_lost",
                    "back online" if online else "no network",
                    {"online": online},
                )
            )
        self._online = online
        return seen

    # -- what the scheduler calls --------------------------------------------

    def look(self, busy_with: str = "") -> list[Reading]:
        """Everything newly worth saying. Empty is the normal answer.

        `busy_with` is what has the machine, when something does. Memory
        pressure while a game is running is not news -- it is the game, and
        complaining about it is complaining about the thing she just stood
        aside for. See `focus`.
        """
        seen: list[Reading] = []
        watchers = [self._look_at_disks, self._look_at_power, self._look_at_network]
        if not busy_with:
            # Memory only when nothing is expected to be eating it.
            watchers.insert(2, self._look_at_memory)
        else:
            # Remembered as reported, so that when the game closes and memory
            # is genuinely still high she does not announce it as new.
            self._memory = True
        for watcher in watchers:
            try:
                seen.extend(watcher())
            except Exception as exc:
                # One sensor failing is not the others failing. Named, because
                # a watcher that silently stopped watching is the failure this
                # whole module exists to notice in other things.
                log.warning(
                    "machine: %s failed (%s); the rest still looked",
                    watcher.__name__.removeprefix("_look_at_"),
                    str(exc)[:160],
                )
        if seen:
            self._save()
            log.info(
                "machine: %s", "; ".join(reading.summary for reading in seen),
                extra={"marvi_readings": len(seen)},
            )
        return seen
