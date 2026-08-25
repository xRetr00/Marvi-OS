"""Foreground Voice-session presence for proactive policy suppression."""

from __future__ import annotations

import threading

_lock = threading.Lock()
_active = False


def report(active: bool) -> bool:
    global _active
    with _lock:
        _active = active
        return _active


def active() -> bool:
    with _lock:
        return _active


def reset() -> None:
    """Tests and Gateway shutdown clear process-local session state."""
    global _active
    with _lock:
        _active = False
