"""A copy of a file from just before Marvi changed it.

`file_write`, `file_edit` and `file_delete` said "this cannot be undone", and
from a voice turn or a Harvi job that was literally true: the old bytes were
gone the moment the tool returned. Hermes Agent answers the same problem with a
shadow git store and `/rollback` (MIT, design reference only, no code taken).

This is the smaller version of that idea. Before one of Marvi's own file tools
changes an existing file, its current bytes are copied here; `file_restore`
puts them back. Restoring takes a checkpoint first, so a restore is itself
undoable.

What it does not cover, on purpose:

* **Commands.** `terminal_run` can change anything; only the file tools are
  checkpointed. A snapshot of every file a shell command might touch is the
  shadow-repository design, and it is a separate piece of work.
* **Folders.** `file_delete` on a folder is not copied.
* **Large files.** Anything over `MAX_BYTES` is not copied; the tool result
  says so rather than pretending.

# ponytail: flat folder + JSON index capped at KEEP entries; move to a
# content-addressed store if checkpoints of the same large files pile up.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import paths

#: A snapshot bigger than this is skipped. Workspace files are text; a 20 MB
#: file is a build artifact or a dataset, and copying it on every edit is waste.
MAX_BYTES = 20 * 1024 * 1024

#: The newest this many checkpoints are kept; older ones are deleted.
KEEP = 200

_lock = threading.Lock()


def folder() -> Path:
    return paths.root() / "checkpoints"


def _index_path() -> Path:
    return folder() / "index.json"


def _read_index() -> list[dict[str, Any]]:
    try:
        rows = json.loads(_index_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


def _write_index(rows: list[dict[str, Any]]) -> None:
    folder().mkdir(parents=True, exist_ok=True)
    temporary = _index_path().with_suffix(".tmp")
    temporary.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    temporary.replace(_index_path())


def save(target: Path, action: str) -> dict[str, Any] | None:
    """Copy `target` before `action` changes it. None when there is nothing to keep."""
    if not target.is_file():
        return None
    size = target.stat().st_size
    if size > MAX_BYTES:
        return {"skipped": f"{size} bytes is over the {MAX_BYTES} byte checkpoint limit"}
    with _lock:
        folder().mkdir(parents=True, exist_ok=True)
        checkpoint = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
        (folder() / f"{checkpoint}.bin").write_bytes(target.read_bytes())
        row = {
            "id": checkpoint,
            "path": str(target.resolve()),
            "action": action,
            "bytes": size,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        rows = [*_read_index(), row]
        for old in rows[:-KEEP]:
            (folder() / f"{old['id']}.bin").unlink(missing_ok=True)
        _write_index(rows[-KEEP:])
    return row


def listing(target: Path | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Newest first, optionally for one file."""
    rows = _read_index()
    if target is not None:
        wanted = str(target.resolve())
        rows = [row for row in rows if row.get("path") == wanted]
    return list(reversed(rows))[: max(1, limit)]


def restore(target: Path, checkpoint: str = "") -> dict[str, Any]:
    """Put a checkpoint's bytes back at `target`: the named one, else the newest."""
    candidates = listing(target, limit=KEEP)
    chosen = next((row for row in candidates if not checkpoint or row["id"] == checkpoint), None)
    if chosen is None:
        raise FileNotFoundError(
            f"no checkpoint {checkpoint!r} for {target}" if checkpoint else f"no checkpoint for {target}"
        )
    blob = folder() / f"{chosen['id']}.bin"
    if not blob.is_file():
        raise FileNotFoundError(f"checkpoint {chosen['id']} has no stored copy any more")
    # The current state first, so undoing the undo is possible.
    before = save(target, "restore")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob.read_bytes())
    return {
        "restored": chosen["id"],
        "from": chosen["at"],
        "bytes": chosen["bytes"],
        "previous_saved_as": (before or {}).get("id", ""),
    }
