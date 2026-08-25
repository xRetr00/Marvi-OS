"""Die when the thing that started you dies.

Marvi's services are started by the desktop and stopped by it on the way out.
That works when the desktop gets to run its shutdown, and it is the case that
does not matter: a clean quit was never the problem. What leaves a Gateway
holding port 8765 overnight is the desktop being killed, crashing, or losing
power -- and then nothing runs the code that would have stopped anything.

The result is a process nobody owns: it holds the port, the next Marvi cannot
bind, and the shell shows a boot failure over a Gateway that is running
perfectly and belongs to a session that ended hours ago.

## Why a watchdog rather than tidier shutdown

There is no shutdown to tidy. The parent did not exit, it stopped existing.
Anything that depends on the parent running code at the end cannot cover the
case, so the child has to notice on its own.

Windows has a proper answer for this -- a job object with
`KILL_ON_JOB_CLOSE`, which makes the kernel do it -- and reaching it from
Electron needs native bindings. This needs a thread and a pid.

## Not a supervisor

It does not restart anything, report anything, or decide whether the parent
*should* have died. One question, once a second: is that process still there.
"""

from __future__ import annotations

import os
import threading
import time

from .logs import get_logger

log = get_logger("gateway")

#: The desktop puts its own process id here when it spawns a service.
PARENT_ENV = "MARVI_PARENT_PID"

#: Long enough that a busy machine is never mistaken for a dead parent, short
#: enough that a port is not held for a noticeable time after one.
CHECK_SECONDS = 2.0


def _alive(pid: int) -> bool:
    """Whether a process id is still running.

    On Windows `os.kill(pid, 0)` raises for a process that exists but is not
    ours to signal, so this asks the kernel for a handle instead: the question
    is existence, not permission.
    """
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def watch(pid: int | None = None, on_gone: object = None) -> threading.Thread | None:
    """Exit this process when `pid` stops existing. Returns the watcher.

    None when there is nothing to watch, which is the normal case for a service
    started by hand: a developer running the Gateway in a terminal has not
    asked for it to die when anything else does.
    """
    parent = pid if pid is not None else int(os.environ.get(PARENT_ENV, "0") or 0)
    if not parent or not _alive(parent):
        return None

    def wait() -> None:
        while _alive(parent):
            time.sleep(CHECK_SECONDS)
        log.warning(
            "the process that started this one is gone; shutting down",
            extra={"marvi_parent": str(parent)},
        )
        if callable(on_gone):
            on_gone()
        # `os._exit` rather than `sys.exit`: this is a daemon thread, and a
        # SystemExit raised here would be caught by the thread and ignored,
        # which is precisely the outcome being fixed.
        os._exit(0)

    watcher = threading.Thread(target=wait, name="parent-watchdog", daemon=True)
    watcher.start()
    log.info("watching the parent process", extra={"marvi_parent": str(parent)})
    return watcher
