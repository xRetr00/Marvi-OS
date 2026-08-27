"""Resolve MARVI_MESSAGING_HOME for standalone skill scripts.

Skill scripts may run outside the Marvi process (e.g. system Python,
nix env, CI) where ``marvi_constants`` is not importable.  This module
provides the same ``get_marvi_home()`` and ``display_marvi_home()``
contracts as ``marvi_constants`` without requiring it on ``sys.path``.

When ``marvi_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``marvi_constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating the ``MARVI_MESSAGING_HOME = Path(os.getenv(...))`` pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from marvi_constants import display_marvi_home as display_marvi_home
    from marvi_constants import get_marvi_home as get_marvi_home
except (ModuleNotFoundError, ImportError):

    def get_marvi_home() -> Path:
        """Return the Marvi home directory (default: ~/.marvi).

        Mirrors ``marvi_constants.get_marvi_home()``."""
        val = os.environ.get("MARVI_MESSAGING_HOME", "").strip()
        return Path(val) if val else Path.home() / ".marvi"

    def display_marvi_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``marvi_constants.display_marvi_home()``."""
        home = get_marvi_home()
        try:
            return "~/" + str(home.relative_to(Path.home()))
        except ValueError:
            return str(home)
