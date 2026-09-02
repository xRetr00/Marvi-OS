"""Background threads that died, so a lost capability is not a silent one.

A thread dying uncaught was logged and nothing more. That is enough when the
thread was doing something optional and not enough when it was the only thing
supervising a subsystem.

`smart_room_supervisor` is the case that prompted this. It is the plugin's own
crash monitor: it polls the room runtime, restarts it when it stops, and is the
only thing that does. Its liveness check ends in `sock.recv`, which raises when
the runtime restarts or the socket resets, and the plugin catches that around
the *restart* but not around the *check*. So the supervisor died twice, the
Gateway stayed up, the room stopped being supervised, and nothing anywhere said
so -- health was green, tools still listed, and the first symptom would be a
light that does not come on.

The plugin's bug is the plugin's to fix -- `_supervise_loop` should treat a
socket error as "not alive" rather than as fatal. What is Marvi's to fix is
noticing. A capability whose supervisor is gone is degraded, and `/health` is
where a person looks.

## Why by thread name

The host does not own these threads and cannot ask a plugin which ones matter.
The name is what a thread carries across that boundary, and plugins name their
threads after themselves -- `smart_room_supervisor` says both what died and
whose it was. A convention, not a contract, which is why an unrecognised name
is still recorded and simply not attributed to anything.
"""

from __future__ import annotations

import threading
import time
from typing import Any

#: Threads whose name begins with one of these belong to a subsystem whose
#: loss is worth reporting rather than merely logging.
WATCHED = ("smart_room", "marvi-")

#: How many to keep. This is a list of accidents; a long one is a symptom in
#: itself and reading the log is the way to study it.
KEEP = 20

_lock = threading.Lock()
_dead: list[dict[str, Any]] = []


def died(name: str, error: BaseException | None = None) -> None:
    """Record a thread that ended on an exception. Never raises."""
    with _lock:
        _dead.append(
            {
                "thread": str(name or "?"),
                "error": f"{type(error).__name__}: {error}" if error else "",
                "at": round(time.time(), 3),
                # Whether anything should act on it, decided here rather than
                # at the call site: the excepthook runs for every thread in the
                # process and should not need to know which ones matter.
                "supervisory": str(name or "").startswith(WATCHED),
            }
        )
        del _dead[:-KEEP]


def losses() -> list[dict[str, Any]]:
    """Every recorded death, newest last."""
    with _lock:
        return list(_dead)


def degraded() -> list[str]:
    """The names of supervisory threads that are gone and have not come back.

    A thread that died and was restarted under the same name is not a loss, so
    the live thread set is checked rather than the record alone.
    """
    alive = {thread.name for thread in threading.enumerate()}
    with _lock:
        return sorted(
            {
                str(row["thread"])
                for row in _dead
                if row.get("supervisory") and row["thread"] not in alive
            }
        )


def forget() -> None:
    """For tests."""
    with _lock:
        _dead.clear()
