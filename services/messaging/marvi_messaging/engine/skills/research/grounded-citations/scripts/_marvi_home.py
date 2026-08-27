"""Resolve MARVI_MESSAGING_HOME for standalone skill scripts.

Skill scripts may run outside the Marvi process (system Python, nix env,
CI) where ``marvi_constants`` is not importable.  This module provides the
same ``get_marvi_home()`` contract without requiring it on ``sys.path``.

When ``marvi_constants`` IS available it is used directly so profile
resolution and any future enhancements are picked up automatically.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from marvi_constants import get_marvi_home as get_marvi_home
except (ModuleNotFoundError, ImportError):

    def get_marvi_home() -> Path:
        """Return the Marvi home directory (default: ``~/.marvi``)."""
        val = os.environ.get("MARVI_MESSAGING_HOME", "").strip()
        return Path(val) if val else Path.home() / ".marvi"
