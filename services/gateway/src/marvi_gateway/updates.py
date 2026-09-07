"""Terminal adapter for Marvi's repository-owned updater.

The bootstrap remains the only component that checks, builds, rolls back, and
relaunches an installation. This module only finds the installed pieces and
hands an update request to Electron. Going through Electron matters when the
desktop is already running: its single-instance handler can stop services and
quit cleanly before the bootstrap touches the checkout.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from . import paths

UPDATE_FLAG = "--update"


def bootstrap_path() -> Path | None:
    """The installed bootstrap, with the same explicit override as Electron."""
    override = os.environ.get("MARVI_BOOTSTRAP_EXE", "").strip()
    candidates = [Path(override)] if override else []
    candidates.append(paths.root() / "bin" / "marvi-bootstrap.exe")
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def desktop_path(install_root: Path) -> Path | None:
    """The packaged desktop which owns the graceful updater handoff."""
    candidate = install_root / "apps" / "desktop" / "dist" / "win-unpacked" / "Marvi-OS.exe"
    return candidate if candidate.is_file() else None


def channel() -> str:
    """Read the shared update preference; accept the former ``dev`` spelling."""
    try:
        saved = (paths.root() / ".marvi-update-channel").read_text(encoding="utf-8-sig")
    except OSError:
        return "release"
    return "nightly" if saved.strip().lower() in {"nightly", "dev"} else "release"


def check(bootstrap: Path, install_root: Path, selected_channel: str) -> dict[str, Any]:
    """Ask the bootstrap what an update would do without changing the checkout."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [
                str(bootstrap),
                "check",
                "--install-root",
                str(install_root),
                "--channel",
                selected_channel,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            errors="replace",
            timeout=60,
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": f"could not run the update check: {exc}"}

    try:
        found = json.loads(completed.stdout)
    except (TypeError, ValueError):
        detail = completed.stderr.strip() or "the updater returned an unreadable response"
        return {"error": detail}
    return found if isinstance(found, dict) else {"error": "the updater returned an invalid response"}


def launch(desktop: Path, install_root: Path) -> None:
    """Send ``--update`` through Electron's single-instance handoff."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    subprocess.Popen(
        [str(desktop), UPDATE_FLAG],
        cwd=install_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
    )
