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


LAUNCH_ENV = "MARVI_LAUNCH_ID"


#: Told apart on purpose. "There is no record" and "the record could not be
#: read" look the same to a `try/except` and mean opposite things: the first is
#: a shutdown that has begun, the second is a file being rewritten under us.
GONE = "gone"
UNREADABLE = "unreadable"


def _launch_on_disk() -> str | None:
    """The launch that owns this machine, or `GONE`/`UNREADABLE`.

    A plain None for both was the first version of this and it was wrong in a
    way that would have taken the whole stack down: the record is rewritten on
    every child start, a reader landing mid-write gets half a file, and
    treating that as "no record" makes every child conclude the desktop has
    shut down and exit together.
    """
    from .paths import root

    path = root() / "state" / "runtime.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return GONE
    except OSError:
        return UNREADABLE
    try:
        import json

        found = json.loads(raw)
    except ValueError:
        return UNREADABLE
    launch = found.get("launchId") if isinstance(found, dict) else None
    return str(launch) if isinstance(launch, str) and launch else UNREADABLE


def _superseded(mine: str) -> bool:
    """Whether a newer launch has taken over, or the shutdown has begun.

    Only two answers end this process: the record is gone (the desktop removes
    it before stopping its children) or it names a different launch. Anything
    unreadable is "ask again later" -- a file being rewritten is not a reason
    to stand down, and the parent-PID check below still covers a desktop that
    died without tidying.
    """
    if not mine:
        return False
    current = _launch_on_disk()
    if current == UNREADABLE:
        return False
    return current != mine


def watch(pid: int | None = None, on_gone: object = None) -> threading.Thread | None:
    """Exit when the launch that started this process is over. Returns the watcher.

    Three conditions, and the first two are new. Watching the parent PID alone
    was an inference: PIDs are recycled, so "my parent is alive" was true of a
    parent that had exited and whose number now belonged to something else --
    and the Gateway that outlived its desktop stayed up on the strength of it,
    refusing the Agent its credentials 285 times.

    * the ownership record names a different launch -> a newer one owns the
      machine, stand down
    * the record has gone -> the desktop is shutting down and removed it first
    * the parent PID no longer exists -> the desktop died without tidying

    None when there is nothing to watch, which is the normal case for a service
    started by hand: a developer running the Gateway in a terminal has not
    asked for it to die when anything else does.
    """
    parent = pid if pid is not None else int(os.environ.get(PARENT_ENV, "0") or 0)
    mine = os.environ.get(LAUNCH_ENV, "").strip()
    if not parent or not _alive(parent):
        return None

    def wait() -> None:
        # Twice in a row before acting. The record is replaced by a rename, and
        # a reader that lands in the gap sees no file at all -- which is the
        # same thing a shutdown looks like. One check apart is enough to tell
        # a rename from a departure.
        confirmations = 0
        while _alive(parent):
            confirmations = confirmations + 1 if _superseded(mine) else 0
            if confirmations >= 2:
                log.warning(
                    "a newer launch owns this machine; shutting down",
                    extra={"marvi_launch": mine},
                )
                break
            time.sleep(CHECK_SECONDS)
        else:
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
