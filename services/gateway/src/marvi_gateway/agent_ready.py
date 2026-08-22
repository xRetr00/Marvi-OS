"""Whether the voice worker is registered and could take a job.

The Gateway could not see the Agent at all. It checked that LiveKit was running
and the speech models were on disk, and called voice "ready" on that basis --
so Join was pressable during the eighteen seconds the worker spends loading
those models into the GPU.

That window is not cosmetic. LiveKit dispatches a job when the room is created;
if no worker is registered at that moment there is no agent, and none is
dispatched when one registers a moment later. The session sits there, connected,
with nobody in it, and the only way out is to leave and join again.

So the Agent says. In memory on purpose: this describes a process that is either
running now or is not, and a value that outlived the process it described would
be worse than no value at all.
"""

from __future__ import annotations

import time
from typing import Any

#: A worker that registered and then died without saying so leaves this stale.
#: The Agent posts on start as well as on registration, and the desktop restarts
#: it on exit, so the window is small -- but not zero, which is why the age is
#: reported rather than hidden.
_ready = False
_detail = ""
_at = 0.0


def set(ready: bool, detail: str = "") -> None:  # noqa: A001 - the verb is the point
    global _ready, _detail, _at
    _ready, _detail, _at = ready, detail, time.time()


def forget() -> None:
    """For tests, and for a Gateway that has just started and knows nothing."""
    set(False, "")


def status() -> dict[str, Any]:
    return {
        "ready": _ready,
        "detail": _detail,
        "since": _at or None,
        "age_seconds": (time.time() - _at) if _at else None,
    }
