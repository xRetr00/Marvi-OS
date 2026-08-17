"""The setup system: what Marvi can install, and how.

One engine, two front ends. The desktop app calls it over HTTP; the `marvi` CLI
calls these functions in-process. That matters because **the desktop app cannot
fix the desktop app** — when Electron will not start or the Gateway will not
bind, a button is unreachable and a terminal is not.

Components are data (`config/components.json`), not code.
"""

from __future__ import annotations

from . import firstrun, hardware, mcp, skills, store
from .catalog import Component, FileSpec, for_capability, get, install_root, load

# The module is `installer` and the function is `install`; naming both the
# same shadows one with the other, which is exactly the sort of thing that
# wastes ten minutes at the wrong moment.
from .installer import (
    InstallError,
    Outcome,
    disk_space_for,
    install,
    plan,
    remove,
    verify,
)

__all__ = [
    "Component",
    "FileSpec",
    "InstallError",
    "Outcome",
    "disk_space_for",
    "firstrun",
    "for_capability",
    "get",
    "hardware",
    "install",
    "install_root",
    "load",
    "mcp",
    "plan",
    "remove",
    "skills",
    "store",
    "verify",
]
