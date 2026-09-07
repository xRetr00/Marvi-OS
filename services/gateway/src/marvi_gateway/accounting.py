"""What Marvi is costing this machine, and what she was doing at the time.

Every diagnosis in this system has come down to the same two questions asked
together -- how much is she holding, and what was she doing when she took it --
and until now both had to be answered by hand, from outside, after the fact.

The game stutter is the worked example. Finding it took `nvidia-smi`, a
PowerShell performance counter, `psutil` and four log files, and the answer was
one line long: two Python processes were holding 5,038 MB of a 12 GB card and
5,924 MB of 16 GB of memory, from launch to shutdown, whether or not anybody had
spoken to her that day. Every number needed to say that was available the whole
time. Nothing was recording it.

So this records it. On a timer, and -- more usefully -- on every change of what
she is doing, because the interesting readings are never in the middle of a
steady state. They are at the edges: the moment a model loads, the moment a
match starts, the moment she stands down.

## What a reading is

A row per Marvi process (memory, CPU, disk, and where it can be told, video
memory), the machine's own totals, and a label saying what she was doing. The
label is the part that makes the rest worth keeping -- 3.2 GB of video memory
is a fact, and "3.2 GB of video memory while idle, for the ninth hour" is a bug
report.

## Why per-process video memory is awkward

`nvidia-smi` will not attribute video memory per process under Windows' display
driver model; it answers `[N/A]` for every row, which is how the 5 GB stayed
invisible. Windows itself knows, through the `GPU Process Memory` performance
counter, and reading that means a PowerShell process -- around half a second.

Too expensive for every tick and too valuable to leave out, so it is read on
phase changes and roughly every five minutes, and every reading says whether it
has that number or not. A blank is honest; a stale one would not be.

## Why it is a file rather than a table

It is written from a scheduler thread, read by a page, and its whole purpose is
to survive the crash or the restart that made somebody go looking. Append-only
lines on disk are the shape that has never lost anybody an incident.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .logs import get_logger

log = get_logger("mind")

#: How often a reading is taken when nothing is changing. Cheap ones only.
EVERY_SECONDS = 30.0

#: And how often the expensive video-memory read happens on its own, when no
#: phase change has forced one. Five minutes: enough to catch a slow leak,
#: rare enough that the PowerShell spawn is not itself the problem.
DEEP_EVERY_SECONDS = 300.0

#: Readings kept on disk. At one every thirty seconds this is about twelve
#: hours, which covers "what happened last night" without becoming a database.
MOST_KEPT = 1_500

#: What each Marvi process is called. Every marker in a row must appear in the
#: command line for it to count, and the first row that matches wins.
#:
#: Every one of these is deliberately specific. The first version matched on
#: `"wake"` alone and promptly attributed 506 MB of a Claude Code renderer to
#: Marvi's wake word -- which is worse than having no number, because a wrong
#: number sends somebody to look at the wrong process. `runtime.app` carries
#: the same risk from the other direction: it is a common enough module name
#: that it has to be paired with the install path before it means the room.
KNOWN: tuple[tuple[tuple[str, ...], str], ...] = (
    (("marvi_gateway.app",), "gateway"),
    (("marvi_agent.session",), "agent"),
    (("marvi_tts_voxtream",), "tts-voxtream"),
    (("marvi_tts_",), "tts-sidecar"),
    (("runtime.app", "Marvi-OS"), "room"),
    (("marvi-wake-host",), "wake-word"),
    (("livekit-server",), "livekit"),
    (("Marvi-OS.exe",), "desktop"),
)


def _mb(value: Any) -> float:
    try:
        return round(float(value) / 1_048_576.0, 1)
    except Exception:
        return 0.0


@dataclass
class Process:
    """One Marvi process, and what it is holding."""

    role: str
    pid: int
    rss_mb: float
    #: Since the last reading, not since the process started -- `psutil`'s
    #: first call always answers 0.0 and the second answers the interval.
    cpu_percent: float
    read_mb: float
    write_mb: float
    #: `None` when this reading did not go looking. See the module docstring:
    #: a blank is honest, a stale number is not.
    vram_mb: float | None = None
    #: Seconds since the process started. A model held for nine hours and a
    #: model held for nine seconds are different problems.
    alive_seconds: float = 0.0


@dataclass
class Doing:
    """What she was doing when the reading was taken."""

    #: From `runtime.AssistantPhase` where there is one -- ready, listening,
    #: thinking, speaking, announcing -- plus the two it has no word for.
    phase: str = "unknown"
    #: The lifecycle moments the phase vocabulary does not cover, because they
    #: are exactly when the expensive things happen.
    moment: str = ""
    voice_ready: bool = False
    in_call: bool = False
    low_resource: bool = False
    #: What has the machine, when something does: "FC 26".
    busy_with: str = ""


@dataclass
class Reading:
    """One moment: what she was doing, and what it cost."""

    at: float
    doing: Doing
    processes: list[Process] = field(default_factory=list)
    #: The machine as a whole, so a Marvi number can be read as a share of it.
    ram_total_mb: float = 0.0
    ram_available_mb: float = 0.0
    cpu_percent: float = 0.0
    vram_total_mb: float = 0.0
    vram_used_mb: float = 0.0
    gpu_percent: float = 0.0
    disk_free_gb: float = 0.0
    #: Whether the expensive per-process video memory read happened.
    deep: bool = False

    def marvi_ram_mb(self) -> float:
        return round(sum(one.rss_mb for one in self.processes), 1)

    def marvi_vram_mb(self) -> float | None:
        held = [one.vram_mb for one in self.processes if one.vram_mb is not None]
        return round(sum(held), 1) if held else None


def _gpu_totals() -> tuple[float, float, float]:
    """Card memory used, total, and utilisation. Zeroes when there is no card."""
    try:
        answer = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        used, total, percent = (part.strip() for part in answer.stdout.split(",")[:3])
        return float(used), float(total), float(percent)
    except Exception:
        return 0.0, 0.0, 0.0


def _vram_by_pid() -> dict[int, float]:
    """Video memory per process, in megabytes. Empty when it cannot be told.

    Through Windows' own performance counter, because `nvidia-smi` refuses:
    under the display driver model it answers `[N/A]` for every process, which
    is precisely why five gigabytes of held video memory went unnoticed for as
    long as it did.

    Instance names look like `pid_5140_luid_0x00000000_0x0000c9b8_phys_0`, and
    a process with memory on more than one adapter appears more than once, so
    they are summed rather than taken.
    """
    if os.name != "nt":
        return {}
    script = (
        "(Get-Counter '\\GPU Process Memory(*)\\Local Usage' -EA SilentlyContinue)."
        "CounterSamples | ForEach-Object { \"$($_.InstanceName)=$($_.CookedValue)\" }"
    )
    try:
        answer = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        log.info("could not read per-process video memory (%s)", str(exc)[:120])
        return {}
    found: dict[int, float] = {}
    for line in answer.stdout.splitlines():
        name, _, value = line.partition("=")
        if not name.startswith("pid_") or not value.strip():
            continue
        try:
            pid = int(name.split("_")[1])
            found[pid] = found.get(pid, 0.0) + float(value) / 1_048_576.0
        except (IndexError, ValueError):
            continue
    return found


def _role(command: str, name: str) -> str:
    """Which part of Marvi this is, or empty for a process that is not hers."""
    haystack = f"{command} {name}"
    for markers, role in KNOWN:
        if all(marker in haystack for marker in markers):
            return role
    return ""


class Accountant:
    """Takes readings, keeps the recent ones, and writes them down.

    The phase is pushed in rather than pulled: the things that know what she is
    doing -- the runtime store, the agent's ready report, the focus watcher --
    already exist and already change at the right moments, so this listens
    instead of polling them.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._recent: list[Reading] = []
        #: `psutil.Process` handles kept between readings, because CPU percent
        #: is meaningless on a fresh handle -- the first call always answers
        #: zero and the second answers the interval since the first.
        self._handles: dict[int, Any] = {}
        self._last_deep = 0.0
        #: What the last reading said she was doing, so a change can force one.
        self._was = ""
        #: Filled in by whoever knows. See `told`.
        self._doing = Doing()
        self._load()

    # -- what the rest of the Gateway tells it -------------------------------

    def told(self, **facts: Any) -> None:
        """Update what she is doing. Any subset of `Doing`'s fields.

        A change of phase takes a reading immediately, on a thread. The whole
        point of this module is the edges -- a 438MB model arriving, a match
        starting, a card being handed back -- and a thirty-second timer walks
        straight past all of them.
        """
        with self._lock:
            for name, value in facts.items():
                if hasattr(self._doing, name):
                    setattr(self._doing, name, value)
            now = f"{self._doing.phase}/{self._doing.moment}/{self._doing.low_resource}"
            changed, self._was = now != self._was, now
        if changed:
            threading.Thread(
                target=self._sample_quietly, name="marvi-accounting", daemon=True
            ).start()

    def _sample_quietly(self) -> None:
        try:
            self.look(deep=True)
        except Exception as exc:  # pragma: no cover - depends on the machine
            log.info("could not take a resource reading (%s)", str(exc)[:160])

    # -- the reading ---------------------------------------------------------

    def look(self, deep: bool | None = None) -> Reading:
        """Take a reading. `deep` also reads per-process video memory."""
        import psutil

        if deep is None:
            deep = (time.time() - self._last_deep) >= DEEP_EVERY_SECONDS
        vram = _vram_by_pid() if deep else {}
        if deep:
            self._last_deep = time.time()

        memory = psutil.virtual_memory()
        used, total, percent = _gpu_totals()
        with self._lock:
            doing = Doing(**asdict(self._doing))
        reading = Reading(
            at=time.time(),
            doing=doing,
            ram_total_mb=_mb(memory.total),
            ram_available_mb=_mb(memory.available),
            cpu_percent=psutil.cpu_percent(interval=None),
            vram_used_mb=used,
            vram_total_mb=total,
            gpu_percent=percent,
            deep=bool(deep),
        )
        try:
            import shutil

            reading.disk_free_gb = round(shutil.disk_usage(Path.home().anchor).free / 1e9, 1)
        except Exception:
            pass

        seen: set[int] = set()
        for entry in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
            try:
                command = " ".join(entry.info.get("cmdline") or ())
                role = _role(command, str(entry.info.get("name") or ""))
                if not role:
                    continue
                pid = int(entry.info["pid"])
                seen.add(pid)
                handle = self._handles.get(pid) or entry
                self._handles[pid] = handle
                with handle.oneshot():
                    rss = handle.memory_info().rss
                    cpu = handle.cpu_percent(interval=None)
                    try:
                        io = handle.io_counters()
                        read, wrote = io.read_bytes, io.write_bytes
                    except Exception:
                        read = wrote = 0
                reading.processes.append(
                    Process(
                        role=role,
                        pid=pid,
                        rss_mb=_mb(rss),
                        cpu_percent=round(cpu, 1),
                        read_mb=_mb(read),
                        write_mb=_mb(wrote),
                        vram_mb=round(vram[pid], 1) if pid in vram else None,
                        alive_seconds=round(time.time() - float(entry.info["create_time"]), 1),
                    )
                )
            except Exception:
                # A process that ended between the listing and the reading is
                # the normal case, not a failure worth a line in the log.
                continue
        for pid in [held for held in self._handles if held not in seen]:
            self._handles.pop(pid, None)
        reading.processes.sort(key=lambda one: -one.rss_mb)

        with self._lock:
            self._recent.append(reading)
            self._recent = self._recent[-MOST_KEPT:]
        self._write(reading)
        return reading

    # -- the ledger ----------------------------------------------------------

    def _write(self, reading: Reading) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as ledger:
                ledger.write(json.dumps(plain(reading), ensure_ascii=False) + "\n")
        except Exception as exc:  # pragma: no cover - disk
            log.info("could not write the resource ledger (%s)", str(exc)[:120])
            return
        # Trimmed here rather than on a timer, because the only moment the file
        # is known to be the right size is just after something was added.
        try:
            if self.path.stat().st_size > MOST_KEPT * 900:
                lines = self.path.read_text(encoding="utf-8").splitlines()[-MOST_KEPT:]
                self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-MOST_KEPT:]
        except Exception:
            return
        fields = set(Reading.__dataclass_fields__)
        for line in lines:
            try:
                raw = json.loads(line)
                # `plain` adds `marvi_ram_mb` and `marvi_vram_mb` for whoever
                # is reading the file, and `Reading(**raw)` refuses keys it has
                # no field for -- so every line failed to parse and the ledger
                # silently came back empty after every restart.
                raw = {name: value for name, value in raw.items() if name in fields}
                raw["doing"] = Doing(**raw.get("doing", {}))
                raw["processes"] = [Process(**one) for one in raw.get("processes", [])]
                self._recent.append(Reading(**raw))
            except Exception:
                continue
        if self._recent:
            log.info("%d resource readings from before the restart", len(self._recent))

    # -- what the page asks --------------------------------------------------

    def history(self, limit: int = 240) -> list[dict[str, Any]]:
        with self._lock:
            return [plain(one) for one in self._recent[-max(1, min(limit, MOST_KEPT)) :]]

    def summary(self) -> dict[str, Any]:
        """The one-paragraph answer: what she holds, and what she was doing.

        `by_phase` is the whole reason this exists. Averages over a day say
        Marvi uses three gigabytes; the same numbers split by what she was
        doing say she uses three gigabytes *while idle*, which is a different
        sentence and the one that gets something fixed.
        """
        with self._lock:
            recent = list(self._recent)
        if not recent:
            return {"readings": 0, "by_phase": [], "latest": None}
        buckets: dict[str, list[Reading]] = {}
        for one in recent:
            key = one.doing.moment or one.doing.phase
            buckets.setdefault(key, []).append(one)
        by_phase = [
            {
                "doing": name,
                "readings": len(rows),
                "ram_mb": round(sum(r.marvi_ram_mb() for r in rows) / len(rows), 1),
                "cpu_percent": round(
                    sum(sum(p.cpu_percent for p in r.processes) for r in rows) / len(rows), 1
                ),
                "vram_mb": _average_vram(rows),
                "worst_ram_mb": round(max(r.marvi_ram_mb() for r in rows), 1),
            }
            for name, rows in sorted(buckets.items())
        ]
        return {
            "readings": len(recent),
            "since": recent[0].at,
            "by_phase": by_phase,
            "latest": plain(recent[-1]),
        }

    def forget(self) -> None:
        with self._lock:
            self._recent.clear()
        if self.path is not None:
            with contextlib.suppress(Exception):
                self.path.unlink(missing_ok=True)


def _average_vram(rows: list[Reading]) -> float | None:
    held = [value for value in (row.marvi_vram_mb() for row in rows) if value is not None]
    return round(sum(held) / len(held), 1) if held else None


def plain(reading: Reading) -> dict[str, Any]:
    body = asdict(reading)
    body["marvi_ram_mb"] = reading.marvi_ram_mb()
    body["marvi_vram_mb"] = reading.marvi_vram_mb()
    return body
