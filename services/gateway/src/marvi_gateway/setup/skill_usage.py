"""Which skills are used, and what becomes of the ones that are not.

Taken from hermes's Curator, whose first move is the one everything else needs:
**count the uses**. Marvi had no idea which of her skills had ever been read.
"Which of these eleven is worth keeping?" had no answer, so nothing could be
retired and the catalogue could only grow -- and every skill in it costs a line
in the prompt on every turn, which on voice is latency you can hear.

## A sidecar, not frontmatter

hermes's reasoning, and it is right: telemetry in `SKILL.md` would put an
operational counter inside a file the user authored and a bundled skill ships,
so every update would conflict with a number nobody edited. One JSON file
beside the skills, keyed by name.

## The states

    active    the default
    stale     unread for STALE_AFTER days
    archived  unread for ARCHIVE_AFTER days; moved to .archive/
    pinned    opts out of all of it, orthogonal to the rest

Two rules are load-bearing and both are hermes's:

**Never delete, only archive.** Archive is a directory move and is undone by a
directory move. A background pass that deletes what a person wrote is a
background pass nobody can safely leave running.

**Only skills Marvi wrote herself.** A skill the user installed or authored is
theirs; its being unused is not evidence it is unwanted. `learning.py` marks
what it proposes, and only those are ever swept. The same invariant the dreamer
holds over memory: it may withdraw its own conclusions and nothing else.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..logs import get_logger
from ..paths import skills_dir

log = get_logger("setup")

ACTIVE, STALE, ARCHIVED = "active", "stale", "archived"

#: Unread for this long and a skill is stale. Long enough that a skill for
#: something seasonal -- a quarterly report, a yearly renewal -- is not swept
#: between two uses of it.
STALE_AFTER = timedelta(days=60)
ARCHIVE_AFTER = timedelta(days=180)

USAGE_FILE = ".usage.json"
ARCHIVE_DIR = ".archive"


def usage_path(directory: Path | None = None) -> Path:
    return (directory or skills_dir()) / USAGE_FILE


def _read(directory: Path | None = None) -> dict[str, dict[str, Any]]:
    try:
        found = json.loads(usage_path(directory).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _write(records: dict[str, dict[str, Any]], directory: Path | None = None) -> None:
    """Replace the file atomically.

    A half-written counter file is one that reads as "nothing has ever been
    used", and the sweep below acts on that.
    """
    target = usage_path(directory)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(records, indent=2), encoding="utf-8")
        os.replace(temporary, target)
    except OSError as exc:  # pragma: no cover - depends on the filesystem
        log.warning("could not record skill usage: %s", exc)


def _record(records: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    return records.setdefault(
        name, {"uses": 0, "last_used": "", "first_seen": _now(), "mine": False, "pinned": False}
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def used(name: str, directory: Path | None = None) -> None:
    """A skill was read. Best-effort: a broken sidecar never breaks a tool."""
    records = _read(directory)
    entry = _record(records, name)
    entry["uses"] = int(entry.get("uses", 0)) + 1
    entry["last_used"] = _now()
    _write(records, directory)


def mark_mine(name: str, directory: Path | None = None) -> None:
    """Marvi wrote this one, so the sweep may touch it."""
    records = _read(directory)
    _record(records, name)["mine"] = True
    _write(records, directory)


def set_pinned(name: str, pinned: bool, directory: Path | None = None) -> dict[str, Any]:
    records = _read(directory)
    _record(records, name)["pinned"] = bool(pinned)
    _write(records, directory)
    return records[name]


def state(name: str, directory: Path | None = None, now: datetime | None = None) -> str:
    """What this skill's age says about it. Pinned is not a state; it is a veto."""
    entry = _read(directory).get(name)
    if entry is None or entry.get("pinned"):
        return ACTIVE
    stamp = entry.get("last_used") or entry.get("first_seen") or ""
    try:
        since = (now or datetime.now(UTC)) - datetime.fromisoformat(stamp)
    except ValueError:
        return ACTIVE
    if since >= ARCHIVE_AFTER:
        return ARCHIVED
    return STALE if since >= STALE_AFTER else ACTIVE


def describe(names: list[str], directory: Path | None = None) -> dict[str, dict[str, Any]]:
    """Everything the skills page needs about use, per name."""
    records = _read(directory)
    return {
        name: {
            "uses": int((records.get(name) or {}).get("uses", 0)),
            "last_used": (records.get(name) or {}).get("last_used", ""),
            "mine": bool((records.get(name) or {}).get("mine", False)),
            "pinned": bool((records.get(name) or {}).get("pinned", False)),
            "state": state(name, directory),
        }
        for name in names
    }


def archive(name: str, directory: Path | None = None) -> bool:
    """Move a skill out of the way. Recoverable, which is the whole point."""
    base = directory or skills_dir()
    source = base / name
    if not source.is_dir():
        return False
    target = base / ARCHIVE_DIR / name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(source), str(target))
    except OSError as exc:
        log.warning("could not archive %s: %s", name, exc)
        return False
    records = _read(directory)
    _record(records, name)["archived_at"] = _now()
    _write(records, directory)
    log.info("skill archived", extra={"marvi_skill": name})
    return True


def restore(name: str, directory: Path | None = None) -> bool:
    """Bring an archived skill back. The reason archiving is allowed at all."""
    base = directory or skills_dir()
    source = base / ARCHIVE_DIR / name
    if not source.is_dir():
        return False
    try:
        shutil.move(str(source), str(base / name))
    except OSError as exc:
        log.warning("could not restore %s: %s", name, exc)
        return False
    records = _read(directory)
    entry = _record(records, name)
    entry.pop("archived_at", None)
    # Restoring resets the clock. Otherwise it is old the moment it is back and
    # the next sweep takes it again.
    entry["last_used"] = _now()
    _write(records, directory)
    return True


def archived(directory: Path | None = None) -> list[str]:
    base = (directory or skills_dir()) / ARCHIVE_DIR
    if not base.is_dir():
        return []
    return sorted(entry.name for entry in base.iterdir() if (entry / "SKILL.md").is_file())


def sweep(directory: Path | None = None, now: datetime | None = None) -> dict[str, list[str]]:
    """Archive Marvi's own skills that nobody has used in a long time.

    Touches nothing the user installed or wrote, nothing pinned, and deletes
    nothing at all. Returns what it moved and what is close to moving, because
    a sweep that acts silently is one nobody trusts.
    """
    from . import skills as skills_module

    base = directory or skills_dir()
    records = _read(directory)
    moved: list[str] = []
    ageing: list[str] = []
    for skill in skills_module.installed(directory):
        entry = records.get(skill.name) or {}
        if not entry.get("mine") or entry.get("pinned"):
            continue
        # Bundled skills live in the checkout and are not ours to move.
        if skill.path is not None and base not in skill.path.parents:
            continue
        found = state(skill.name, directory, now)
        if found == ARCHIVED and archive(skill.name, directory):
            moved.append(skill.name)
        elif found == STALE:
            ageing.append(skill.name)
    if moved or ageing:
        log.info(
            "skill sweep completed",
            extra={"marvi_archived": len(moved), "marvi_stale": len(ageing)},
        )
    return {"archived": moved, "stale": ageing}
