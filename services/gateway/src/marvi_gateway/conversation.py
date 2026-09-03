"""Foreground Voice-session presence for proactive policy suppression.

This is the guard that stops the mind talking over a live conversation, and it
was a bare module-level bool set by the desktop's *renderer* over IPC. Two ways
that goes wrong, and both are silent:

* it sticks on. The renderer closes, reloads, or crashes without sending
  `false`, and the mind is muted for the life of the Gateway. Nothing anywhere
  says why Marvi stopped speaking.
* it sticks off. The Gateway restarts mid-call and comes back with `False`, so
  the mind is free to interrupt a conversation that is still running.

The fix is the one `agent_ready` already uses one file over: record *when* it
was said, and stop believing it after a while. A voice session that is really
still running keeps saying so; one that ended without a word times out.

## Why a heartbeat rather than a longer timeout

A long timeout trades one failure for the other -- the longer it is, the longer
a crashed renderer keeps Marvi quiet. A short one needs the truth repeated,
which is cheap: the desktop already polls the Gateway several times a minute
for status, and reporting an active session costs one boolean on a request that
was happening anyway.
"""

from __future__ import annotations

import threading
import time

#: How long a report is believed without being repeated.
#:
#: Longer than the desktop's status poll by a wide margin, so an ordinary
#: hiccup never mutes a live call, and short enough that a renderer which died
#: mid-conversation stops silencing the mind within a minute.
TRUSTED_FOR = 45.0

_lock = threading.Lock()
_active = False
_at = 0.0


def report(active: bool) -> bool:
    """Say whether a foreground voice session is running. Refreshes the clock."""
    global _active, _at
    with _lock:
        _active, _at = active, time.monotonic()
        return _active


def active() -> bool:
    """Whether a session is running *and* something said so recently.

    A stale `True` is treated as false, because the failure it prevents --
    Marvi permanently silent with nothing explaining it -- is worse than the
    one it risks, which is a single proactive line landing near the end of a
    call the desktop stopped reporting.
    """
    with _lock:
        if not _active:
            return False
        return (time.monotonic() - _at) <= TRUSTED_FOR


def age() -> float:
    """Seconds since the last report, or -1 when nothing has ever reported.

    Reported rather than hidden, for the same reason `agent_ready` reports it:
    "the mind is quiet because a conversation is active" and "the mind is quiet
    because something said so once and died" look identical from outside.
    """
    with _lock:
        return -1.0 if not _at else time.monotonic() - _at


def state() -> dict[str, object]:
    """What is known, for diagnostics and the Mind page."""
    with _lock:
        said = _active
        since = -1.0 if not _at else time.monotonic() - _at
    return {
        "active": said and (since <= TRUSTED_FOR if since >= 0 else False),
        "reported": said,
        "age_seconds": round(since, 1) if since >= 0 else None,
        "stale": bool(said and since >= 0 and since > TRUSTED_FOR),
        "trusted_for": TRUSTED_FOR,
    }


def reset() -> None:
    """Tests and Gateway shutdown clear process-local session state."""
    global _active, _at
    with _lock:
        _active, _at = False, 0.0
