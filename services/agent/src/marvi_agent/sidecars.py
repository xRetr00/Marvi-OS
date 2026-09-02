"""Every child process holding a model, and how they are made to go away.

Marvi now runs up to four isolated runtimes: CuteTTS, VoXtream, PocketTTS and
the Kyutai recogniser. Each is a `uv run` wrapper around a Python process
holding a model in VRAM, and each was closed only by the code that opened it.

That was survivable with one. With four it is not, because the ways a worker
ends are not all polite:

* the desktop quits and the parent watchdog calls `os._exit(0)`, which runs no
  `atexit` handler and no `finally`
* a job process is replaced after a session
* the engine is changed in Settings, and the old one has no owner left

In every one of those the wrapper was terminated at best and the process under
it was left running -- holding a model on a 12 GB card until the machine was
rebooted. `nvidia-smi` on this machine has shown two abandoned CUDA contexts
from a single afternoon of switching engines.

So: one registry, one way to kill a tree, and one function that means it.

## Why a tree and not a process

`uv run --project x python -m y` is at least two processes: uv, and the Python
it starts. Terminating uv leaves the Python holding the model, which is the
exact failure this exists to prevent. On Windows that means `taskkill /T`,
which is why this is not simply `Popen.terminate()`.

## Why a registry and not a base class

The two kinds of sidecar have nothing else in common -- one streams PCM out,
the other streams text out, and they are built by different code for different
reasons. What they share is a process handle and a debt.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import os
import subprocess
import threading
from typing import Any, Protocol

log = logging.getLogger("marvi.voice")

#: How long a sidecar gets to exit on its own before it is killed outright.
STOP_TIMEOUT = 5.0


class Closable(Protocol):
    def close(self) -> None: ...


_lock = threading.Lock()
_open: list[Any] = []
_hooked = False


def kill_tree(process: subprocess.Popen[Any] | None) -> None:
    """End a sidecar and everything it started.

    `uv run` is a wrapper: terminating it leaves the Python process under it
    holding its model. On Windows the only reliable way down is `taskkill /T`,
    and it is worth the subprocess call -- the alternative is VRAM that is not
    returned until the machine restarts.
    """
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
    else:
        with contextlib.suppress(Exception):
            process.terminate()
    try:
        process.wait(timeout=STOP_TIMEOUT)
    except Exception:
        with contextlib.suppress(Exception):
            process.kill()


def track(sidecar: Closable) -> None:
    """Remember a live sidecar, so something can close it if nothing else does."""
    global _hooked
    with _lock:
        if sidecar not in _open:
            _open.append(sidecar)
        if not _hooked:
            atexit.register(close_all)
            _hooked = True


def forget(sidecar: Closable) -> None:
    """It closed itself. Nothing left to owe."""
    with _lock:
        if sidecar in _open:
            _open.remove(sidecar)


def close_all() -> None:
    """Close every sidecar still open. Safe to call twice, and from anywhere.

    Called from `atexit` for ordinary exits and directly by the parent
    watchdog, which ends with `os._exit(0)` and so runs no handler of its own.
    """
    with _lock:
        going, _open[:] = list(_open), []
    if not going:
        return
    log.info("closing %d sidecar(s)", len(going))
    for sidecar in going:
        # Never raises: this runs while the process is going away, and one
        # stubborn sidecar must not keep the others alive.
        with contextlib.suppress(Exception):
            sidecar.close()


def count() -> int:
    """How many are open. For tests and for the log line on shutdown."""
    with _lock:
        return len(_open)
