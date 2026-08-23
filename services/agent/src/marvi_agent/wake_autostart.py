"""Starting the wake word listener at login, and stopping it.

A wake word that only runs while Marvi is open is a wake word for people who
have already opened Marvi. For it to mean anything it has to be running before
she is, which on Windows means the per-user ``Run`` key.

``Run`` rather than a scheduled task or a service: it runs as the logged-in
user, in that user's session, which is the only context where the microphone is
reachable at all. A service runs in session 0 and cannot hear anything. It also
needs no elevation, so turning the wake word on is a switch in the UI rather
than a consent prompt.

The registration records the full command including where Marvi is installed,
so an update that moves the executable rewrites it. There is nothing to migrate
and nothing to clean up if it goes stale: a command that no longer resolves
simply fails to start, and the UI says the listener is not running.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

#: One name, so enabling twice replaces rather than accumulates.
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "MarviWakeWord"


def interpreter() -> str:
    """The interpreter the Run key should invoke.

    ``pythonw.exe`` when it is there, which on Windows is the whole point: it
    is the GUI-subsystem build of Python and does not get a console. Anything
    launched from the ``Run`` key gets whatever window its executable asks for,
    and there is no "hidden" flag to pass -- so the only way to have no console
    is to run something that never creates one.

    Found from ``sys.executable`` rather than guessed from the project path.
    This module is itself running inside the environment in question, put there
    by the desktop shelling out through uv, so the interpreter beside this one
    is by definition the right one. A layout guess would be a second source of
    truth that only fails once the install moves.

    Falls back to uv when there is no ``pythonw`` -- a console is worse than
    the alternative, and the alternative is no wake word.
    """
    if sys.platform == "win32":
        windowless = Path(sys.executable).with_name("pythonw.exe")
        if windowless.is_file():
            return str(windowless)
    return ""


def command(project: Path, app: Path, threshold: float | None = None, device: str = "") -> str:
    """The command line the Run key holds.

    Two shapes, and the first is preferred. Invoking the environment's
    ``pythonw.exe`` directly leaves nothing to open a window. Going through
    ``uv run`` resolves the environment for us but ``uv.exe`` is a console
    program, so the listener sat behind a terminal on the desktop for the whole
    session -- for a process whose entire job is to be invisible.
    """
    windowless = interpreter()
    if windowless:
        parts = [f'"{windowless}"', "-m", "marvi_agent.wake_daemon", "--app", f'"{app}"']
    else:
        parts = [
            f'"{uv_path()}"',
            "run",
            "--project",
            f'"{project}"',
            "python",
            "-m",
            "marvi_agent.wake_daemon",
            "--app",
            f'"{app}"',
        ]
    if threshold is not None:
        parts += ["--threshold", str(threshold)]
    if device.strip():
        parts += ["--device", f'"{device.strip()}"']
    return " ".join(parts)


def uv_path() -> str:
    configured = os.environ.get("MARVI_UV_PATH", "").strip()
    return configured or "uv"


def _key():
    import winreg

    return winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_WRITE
    )


def enable(
    project: Path, app: Path, threshold: float | None = None, device: str = ""
) -> str:
    """Register the listener, and start it now rather than at the next login.

    Waiting for a reboot to find out whether it works is how a switch that does
    nothing goes unnoticed for a week.
    """
    import winreg

    line = command(project, app, threshold, device)
    with _key() as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, line)
    start_now(line)
    return line


def disable() -> bool:
    """Unregister. True if there was something to remove."""
    import winreg

    try:
        with _key() as key:
            winreg.DeleteValue(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False


def registered() -> str:
    """The registered command, or empty. This is the question the UI asks."""
    import winreg

    try:
        with _key() as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
        return str(value)
    except (FileNotFoundError, OSError):
        return ""


def start_now(line: str) -> None:
    """Launch the listener without waiting for a login.

    Detached and windowless: it outlives whatever enabled it, and a console
    sitting on the desktop for the life of the session is not acceptable for
    something that is meant to be invisible.
    """
    creation = 0
    if sys.platform == "win32":
        creation = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    subprocess.Popen(line, shell=False, creationflags=creation, close_fds=True)


def main(argv: list[str] | None = None) -> int:
    """A command, because the desktop is the one that knows the paths.

    Electron has `setLoginItemSettings`, but it registers *Marvi* at login --
    the opposite of what is wanted here, where the point is that the listener
    runs without her. So the registry work stays in this module and the desktop
    calls it.
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Run the wake word listener at login.")
    parser.add_argument("action", choices=["enable", "disable", "status"])
    parser.add_argument("--app", default="", help="path to Marvi.exe")
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument(
        "--device", default="", help="microphone name; empty means the system default"
    )
    args = parser.parse_args(argv)

    project = Path(__file__).resolve().parents[2]
    if args.action == "enable":
        if not args.app:
            print("--app is required to enable", file=sys.stderr)
            return 2
        print(
            json.dumps(
                {"registered": enable(project, Path(args.app), args.threshold, args.device)}
            )
        )
    elif args.action == "disable":
        print(json.dumps({"removed": disable()}))
    else:
        print(json.dumps({"registered": registered()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
