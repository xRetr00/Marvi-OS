"""Marvi's own disk, kept tidy without anybody asking.

Not a plugin, on purpose. Everything a storage plugin would need already
existed: `machine` watches free space, `doctor` checks it, `logs` rotates by
size, the observation and resource ledgers trim themselves, and `marvi models`
installs and removes components. What was missing was the part that throws
things away on a schedule, and that is this module, run once a day by the
initiative scheduler that already runs everything else.

## What goes on its own, and what is asked

Automatic -- nothing here is anybody's data, and everything regenerates:

* **Leftovers** from engines Marvi no longer has (`_leftover_candidates`).
* **Backups beyond the newest.** One backup per thing: making a new one deletes
  the one before it.
* **Logs, every three days.** The previous cycle's logs are kept as `.1` so the
  last three days can still be read; anything older is deleted.
* **Marvi's temporary files** older than a day.

Asked, because each is a download to get back:

* **Speech engines that are not selected** (`unused_engines`). `marvi storage
  clean --engines` removes them; Settings can install one again.

The package caches (`uv`, `npm`) are cleaned by the installer at the end of
every update, and by `marvi storage clean --caches`. Not here: `uv cache
prune` waits for every running `uv` process to exit, and while Marvi is up
there always is one. See docs/STORAGE.md.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths
from .logs import get_logger

log = get_logger("setup")

#: The checkout this runs from: marvi_gateway -> src -> gateway -> services -> repo.
REPO_ROOT = Path(__file__).resolve().parents[4]

DAY = 86_400.0
#: Logs are cycled this often. The user's rule, not a tuning number.
LOG_CYCLE_SECONDS = 3 * DAY
TEMP_MAX_AGE_SECONDS = DAY
CACHE_TIMEOUT_SECONDS = 30 * 60

#: A rotated log (`agent.log.2`) or the live one (`agent.log`).
LOG_FILE = re.compile(r"\.log(\.\d+)?$")

#: A backup's name is the thing it backs up plus a marker. Everything before
#: the marker is the family; only the newest of a family is kept.
#:
#:     memory.sqlite3.before-dedup-20260907   -> memory.sqlite3
#:     faces.sqlite3.20260912.bak             -> faces.sqlite3
#:     smart_room.before-hermes-move-2026...  -> smart_room
#:     vision-backup-20260904-113413          -> vision
BACKUP = re.compile(r"^(?P<base>.+?)(?:\.before-.+|-backup-.+|\.\d{8}\.bak|\.bak)$")


def _leftover_candidates() -> list[tuple[Path, str]]:
    root = paths.root()
    return [
        (root / "models/tts/vibevoice-realtime-0.5b", "the speech engine before Kokoro"),
        (root / "models/stt/nemotron-3.5", "the old Nemotron export the Rust sidecar used"),
        (root / "models/vision", "the Gateway's face models; the Smart Room owns the camera now"),
        (REPO_ROOT / "services/tts-ctc", "a speech engine Marvi no longer has"),
        (
            root / "plugin-data/smart_room/vision/models/models/buffalo_l.zip",
            "the face-model archive, already unpacked beside it",
        ),
    ]


@dataclass(frozen=True)
class Reclaimable:
    path: Path
    bytes: int
    why: str

    @property
    def gigabytes(self) -> float:
        return self.bytes / 1024**3


def size_of(path: Path) -> int:
    """Bytes under a path. Hardlinked files count every time they appear."""
    try:
        if path.is_file():
            return path.stat().st_size
    except OSError:
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _delete(path: Path) -> int:
    """Remove a file or a directory. Returns the bytes it held, 0 on failure."""
    held = size_of(path)
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as exc:
        # Usually a file a running process holds open. Next pass.
        log.info("storage: could not remove %s (%s)", path, str(exc)[:120])
        return 0
    return held


# -- leftovers ---------------------------------------------------------------


def leftovers() -> list[Reclaimable]:
    """What nothing loads any more. Never deletes anything."""
    return [
        Reclaimable(path, size_of(path), why)
        for path, why in _leftover_candidates()
        if path.exists()
    ]


# -- backups -----------------------------------------------------------------


def _backup_folders() -> list[Path]:
    root = paths.root()
    folders = [root, root / "state", root / "plugin-data"]
    plugin_data = root / "plugin-data"
    if plugin_data.is_dir():
        for plugin in plugin_data.iterdir():
            if plugin.is_dir():
                folders += [plugin, plugin / "vision"]
    return [folder for folder in folders if folder.is_dir()]


def old_backups() -> list[Path]:
    """Every backup except the newest of its family."""
    stale: list[Path] = []
    for folder in _backup_folders():
        families: dict[str, list[Path]] = {}
        for item in folder.iterdir():
            match = BACKUP.match(item.name)
            if match:
                families.setdefault(match["base"], []).append(item)
        for members in families.values():
            members.sort(key=lambda one: one.stat().st_mtime, reverse=True)
            stale += members[1:]
    return stale


# -- logs --------------------------------------------------------------------


def _log_folders() -> list[Path]:
    folders = [paths.logs_dir()]
    plugin_data = paths.root() / "plugin-data"
    if plugin_data.is_dir():
        folders += [plugin for plugin in plugin_data.iterdir() if plugin.is_dir()]
    return [folder for folder in folders if folder.is_dir()]


def cycle_logs() -> int:
    """Delete the previous cycle's logs and start a new one. Returns bytes freed.

    Every rotated file goes; each live log is copied to `.1` and emptied. So
    after a cycle the only history is the three days before it, and a cycle
    later that is gone too.

    Emptied in place rather than renamed: the live files are open in other
    processes (the Agent, LiveKit, the room sidecar), and Windows will not
    rename a file somebody holds -- but every writer here appends, so a file
    truncated under it simply carries on from the start.
    """
    freed = 0
    for folder in _log_folders():
        for item in list(folder.iterdir()):
            if item.is_file() and LOG_FILE.search(item.name) and not item.name.endswith(".log"):
                freed += _delete(item)
        for live in folder.glob("*.log"):
            try:
                held = live.stat().st_size
                if not held:
                    continue
                shutil.copyfile(live, live.with_name(live.name + ".1"))
                with live.open("r+b") as handle:
                    handle.truncate(0)
            except OSError as exc:
                log.info("storage: could not cycle %s (%s)", live.name, str(exc)[:120])
    return freed


# -- temporary files ---------------------------------------------------------


def old_temporary(now: float | None = None) -> list[Path]:
    """Marvi's own `marvi-*` files in the temp folder, older than a day."""
    cutoff = (now or time.time()) - TEMP_MAX_AGE_SECONDS
    found = []
    for item in Path(tempfile.gettempdir()).glob("marvi-*"):
        try:
            if item.stat().st_mtime < cutoff:
                found.append(item)
        except OSError:
            continue
    return found


# -- unused speech engines ---------------------------------------------------


def unused_engines(repo_root: Path | None = None) -> list[tuple[Any, Path, int]]:
    """Installed components of speech engines that are not selected."""
    from .setup import catalog

    root = repo_root or REPO_ROOT
    wanted = catalog.unselected_engine_components()
    found = []
    for component in catalog.load(root):
        if component.name not in wanted:
            continue
        where = (
            root / component.project / ".venv"
            if component.kind == "python"
            else component.target()
        )
        if where.exists():
            found.append((component, where, size_of(where)))
    return found


def remove_unused_engines(repo_root: Path | None = None) -> list[str]:
    from .setup import installer

    root = repo_root or REPO_ROOT
    return [
        f"{component.name}: {installer.remove(component, root).detail}"
        for component, _where, _held in unused_engines(root)
    ]


# -- package caches ----------------------------------------------------------


def _npm() -> str | None:
    bundled = paths.root() / "toolchain" / "node" / ("npm.cmd" if os.name == "nt" else "bin/npm")
    return str(bundled) if bundled.is_file() else shutil.which("npm")


def clean_caches(force: bool = False) -> list[str]:
    """`uv cache prune` and `npm cache verify`. Returns a line for each.

    Both only remove what nothing refers to. `uv cache clean` would empty the
    cache instead, and the next update would download PyTorch again.
    """
    from .doctor import find_uv

    commands = []
    if uv := find_uv():
        commands.append(("uv", [uv, "cache", "prune", *(["--force"] if force else [])]))
    if npm := _npm():
        commands.append(("npm", [npm, "cache", "verify"]))
    said = []
    for name, argv in commands:
        try:
            finished = subprocess.run(
                argv, capture_output=True, text=True, timeout=CACHE_TIMEOUT_SECONDS
            )
            output = (finished.stderr + finished.stdout).strip().splitlines()
            said.append(f"{name}: {output[-1] if output else 'done'}")
        except subprocess.TimeoutExpired:
            said.append(f"{name}: still in use after {CACHE_TIMEOUT_SECONDS // 60} minutes; skipped")
        except OSError as exc:
            said.append(f"{name}: {exc}")
    return said


# -- the daily pass ----------------------------------------------------------


def _state_path() -> Path:
    return paths.root() / "state" / "storage.json"


def _state() -> dict[str, Any]:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def housekeep(now: float | None = None) -> dict[str, Any]:
    """Everything automatic, once. Safe to call as often as anybody likes."""
    now = now or time.time()
    state = _state()
    removed: list[str] = []
    freed = 0

    for entry in leftovers():
        if held := _delete(entry.path):
            freed += held
            removed.append(f"{entry.path.name} ({entry.why})")
    for path in [*old_backups(), *old_temporary(now)]:
        if held := _delete(path):
            freed += held
            removed.append(path.name)

    if now - float(state.get("logs_cycled_at") or 0) >= LOG_CYCLE_SECONDS:
        freed += cycle_logs()
        state["logs_cycled_at"] = now
        removed.append("logs from the previous cycle")

    try:
        free_gb = round(shutil.disk_usage(paths.root()).free / 1024**3, 1)
    except OSError:
        free_gb = None
    report = {"at": now, "freed_bytes": freed, "removed": removed, "free_gb": free_gb}
    state["last"] = report
    try:
        _state_path().parent.mkdir(parents=True, exist_ok=True)
        _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        log.info("storage: could not record the pass (%s)", exc)
    if removed:
        log.info("storage: freed %.1f MB -- %s", freed / 1024**2, "; ".join(removed))
    return report


def last_pass() -> dict[str, Any]:
    return dict(_state().get("last") or {})
