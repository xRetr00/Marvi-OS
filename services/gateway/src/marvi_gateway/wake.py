"""What the wake word is doing, for anyone who wants to know.

The gate had no surface at all. There was no way to see that the model had
loaded, no way to change the threshold without editing an environment
variable, and nothing at all when it fired — so a gate that was silently not
running looked exactly like a gate that was running and never triggered. Both
appear as Marvi ignoring you.

That distinction is the whole point of this module. `armed` says the model is
loaded and Marvi is listening for her name; `heard_at` says she has actually
recognised it, and when.

The state is in memory on purpose. A detection matters for the few seconds
after it happens — long enough for the orb to acknowledge it — and a record of
every time somebody said "Marvi" is a log of when people were in the room,
which is not a thing to keep.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

#: Mirrors the Agent's own defaults. Duplicated rather than imported because
#: the Agent runs in a different Python environment; the test below fails if
#: the two drift.
DEFAULT_THRESHOLD = 0.5
DEFAULT_WINDOW_SECONDS = 30.0

#: How long a detection stays "recent" for the UI. Long enough to be seen,
#: short enough that it does not still be claiming she was called a minute ago.
RECENT_SECONDS = 6.0

_heard_at: float | None = None
_confidence = 0.0


def model_path() -> Path:
    """Where the wake word model is, configured or shipped.

    The shipped one lives beside the Agent's source rather than in the state
    directory: it is part of the build, not something the user installs.
    """
    configured = os.environ.get("MARVI_WAKE_MODEL", "").strip()
    if configured:
        return Path(configured)
    # Relative to this file rather than to an install-root variable: the model
    # ships beside the Agent's source, and that relationship holds in a
    # checkout and in an installation alike. MARVI_INSTALL_ROOT is a test
    # isolation knob and pointing at it here found nothing.
    #   .../services/gateway/src/marvi_gateway/wake.py -> .../services
    services = Path(__file__).resolve().parents[3]
    return services / "agent" / "wakeword" / "marvi.onnx"


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    return default if not raw else raw in ("1", "true", "yes", "on")


def _number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def heard(confidence: float = 0.0) -> None:
    """Record that the wake word just fired."""
    global _heard_at, _confidence
    _heard_at = time.time()
    _confidence = confidence


def forget() -> None:
    """Drop the last detection. For tests, and for turning the gate off."""
    global _heard_at, _confidence
    _heard_at = None
    _confidence = 0.0


def status() -> dict[str, Any]:
    path = model_path()
    enabled = _flag("MARVI_WAKE_WORD", True)
    present = path.is_file()
    age = None if _heard_at is None else time.time() - _heard_at
    return {
        "enabled": enabled,
        "model": str(path),
        "model_present": present,
        # Armed means both: switched on *and* the model is actually there. A
        # missing model leaves Marvi answering every turn rather than deaf, so
        # "enabled but not armed" is a real and reportable state.
        "armed": enabled and present,
        "threshold": _number("MARVI_WAKE_THRESHOLD", DEFAULT_THRESHOLD),
        "window": _number("MARVI_WAKE_WINDOW", DEFAULT_WINDOW_SECONDS),
        "heard_at": _heard_at,
        "heard_seconds_ago": age,
        "recently_heard": age is not None and age <= RECENT_SECONDS,
        "confidence": _confidence,
        "setting": "MARVI_WAKE_WORD",
        "threshold_setting": "MARVI_WAKE_THRESHOLD",
    }
