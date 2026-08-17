"""What Marvi leaves behind when it dies.

The logs already record a crash. The problem is nobody reads a log they have no
reason to open — Marvi restarts, seems fine, and the crash is never mentioned
again. Three of those in a week is a pattern the user never learns about.

So a crash writes one small file, and the next launch reads it, says so once,
and clears it. Not a second log: a flag with enough attached to be worth acting
on.

It is deliberately dumb — one JSON file, written with the simplest call that
could work. Anything cleverer risks failing at exactly the moment the process is
already falling over.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .logs import get_logger, logs_dir, redactor

log = get_logger("gateway")

MAX_CRUMBS = 5


def crumb_path() -> Path:
    return logs_dir().parent / "last-crash.json"


def record(reason: str, detail: str = "", component: str = "gateway") -> Path | None:
    """Write the breadcrumb. Never raises — the process is already in trouble."""
    path = crumb_path()
    try:
        existing = read_all()
        existing.append(
            {
                "at": datetime.now(UTC).isoformat(),
                "component": component,
                "reason": redactor().scrub(reason)[:300],
                "detail": redactor().scrub(detail)[:4000],
                "pid": os.getpid(),
            }
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the last few: one crash is an incident, five is a pattern, and
        # the pattern is the more useful thing to show.
        path.write_text(json.dumps(existing[-MAX_CRUMBS:], indent=2), encoding="utf-8")
        return path
    except Exception:
        return None


def read_all() -> list[dict[str, Any]]:
    try:
        loaded = json.loads(crumb_path().read_text(encoding="utf-8"))
    except Exception:
        # Broad on purpose. Every function in this module promises never to
        # raise, and a path can be unusable in ways that are not OSError — an
        # embedded null byte raises ValueError, for one.
        return []
    return loaded if isinstance(loaded, list) else []


def pending() -> list[dict[str, Any]]:
    """Crashes not yet shown to the user."""
    return read_all()


def clear() -> bool:
    try:
        crumb_path().unlink()
        return True
    except Exception:
        return False


def install(component: str = "gateway") -> None:
    """Leave a breadcrumb on any exit that is not a clean one.

    Chained onto whatever `excepthook` is already installed rather than
    replacing it, so the logging engine still records the traceback in full.
    """
    previous = sys.excepthook

    def on_exception(kind, value, tb) -> None:  # type: ignore[no-untyped-def]
        if not issubclass(kind, KeyboardInterrupt):
            record(
                f"{kind.__name__}: {value}",
                "".join(traceback.format_exception(kind, value, tb)),
                component,
            )
        previous(kind, value, tb)

    sys.excepthook = on_exception


def report_and_clear() -> list[dict[str, Any]]:
    """Called at startup: say what happened last time, then forget it.

    Cleared on read so the same crash is not reported every launch forever.
    """
    crumbs = pending()
    for crumb in crumbs:
        log.warning(
            "Marvi did not shut down cleanly last time: %s", crumb.get("reason", "?"),
            extra={"marvi_when": crumb.get("at", ""), "marvi_component": crumb.get("component", "")},
        )
    if crumbs:
        clear()
    return crumbs
