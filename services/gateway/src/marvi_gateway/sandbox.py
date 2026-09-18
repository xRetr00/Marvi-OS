"""Running a snippet of Python with limits, in a directory of its own.

`terminal_run` runs as the user, in the workspace, with everything the user
can reach. That is right for "run the tests" and wrong for "try this and see" --
a loop that allocates until the machine swaps, a script that writes where it
was not asked to, a snippet that never returns.

This is the smaller, bounded thing: one file of Python, in a scratch directory,
under a Windows **Job Object** that caps memory and process count and kills
everything in it when the job handle closes. The interpreter runs isolated
(`-I`): no user site packages, no `PYTHON*` environment, no implicit sys.path
from the caller.

## What this is not

**It is not a security boundary against hostile code.** A Job Object limits
*resources*; it does not stop a determined script reading `%USERPROFILE%` or
reaching the network -- `ctypes` alone defeats any in-interpreter guard. Doing
that properly needs an AppContainer (a lowbox token, a capability set, and a
per-call firewall rule), which is its own piece of work and is recorded as such
in `docs/backlog/big.md`.

So the honest description, and the one the tool gives the model, is: a scratch
pad that cannot run away with the machine. Marvi's own experiments, a bit of
arithmetic, a data file reshaped. Not a place to run something a stranger sent.

The network guard below follows from that: it stops a snippet reaching out *by
accident*, which is the common case, and says plainly that it is not a wall.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path
from typing import Any

from .logs import get_logger

log = get_logger("gateway")

#: How long a snippet may run before it is killed, and the ceiling a caller
#: may ask for.
DEFAULT_TIMEOUT = 20
MAX_TIMEOUT = 120

#: Memory for the whole job. Enough for pandas on a small file; far below the
#: point where the machine starts swapping.
MEMORY_LIMIT = 512 * 1024 * 1024

#: The snippet plus anything it spawns. Four, so a subprocess call works and a
#: fork bomb does not.
PROCESS_LIMIT = 4

#: What comes back. A snippet that prints a megabyte gets its first lines.
MAX_OUTPUT = 20_000

#: Prepended to every snippet. Two lines, and both are about mistakes rather
#: than attacks: `socket` raising is what turns "it quietly tried to download
#: something" into an error the caller can read.
PREAMBLE = """import sys as _sys

def _no_network(*_a, **_k):
    raise OSError(
        "this sandbox has no network. Use Marvi's web tools for that, "
        "or terminal_run if the script genuinely needs to reach out."
    )

try:
    import socket as _socket
    _socket.socket = _no_network
    _socket.create_connection = _no_network
except Exception:
    pass
"""

JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
PROCESS_ALL_ACCESS = 0x1F0FFF


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class SandboxUnavailableError(Exception):
    """There is nothing here that can run a snippet under limits."""


def _job(memory: int = MEMORY_LIMIT, processes: int = PROCESS_LIMIT) -> Any:
    """A Job Object with the limits set, or None where there are no jobs."""
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise SandboxUnavailableError("Windows would not create a job object")
    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = (
        JOB_OBJECT_LIMIT_PROCESS_MEMORY
        | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        # Everything in the job dies with the handle, including anything the
        # snippet started. This is what makes a timeout mean something.
        | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    )
    limits.ProcessMemoryLimit = memory
    limits.BasicLimitInformation.ActiveProcessLimit = processes
    if not kernel32.SetInformationJobObject(
        handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, ctypes.byref(limits),
        ctypes.sizeof(limits),
    ):
        kernel32.CloseHandle(handle)
        raise SandboxUnavailableError("Windows refused the job limits")
    return handle


def run(code: str, timeout: int = DEFAULT_TIMEOUT, memory: int = MEMORY_LIMIT) -> dict[str, Any]:
    """Run one snippet and report what it printed. Never raises for the snippet.

    The scratch directory is the working directory and is deleted afterwards,
    so a snippet that writes `out.csv` gets a real file while it runs and
    leaves nothing behind. A file it should keep goes in the workspace, through
    the file tools, where the checkpoint and confirmation rules apply.
    """
    seconds = max(1, min(int(timeout), MAX_TIMEOUT))
    scratch = Path(tempfile.mkdtemp(prefix="marvi-sandbox-"))
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None
    handle = _job(memory)
    try:
        (scratch / "snippet.py").write_text(PREAMBLE + "\n" + code, encoding="utf-8")
        started = subprocess.Popen(
            # `-I` is the isolation that costs nothing: no user site packages,
            # no `PYTHON*` variables, no cwd on `sys.path`.
            [sys.executable, "-I", "snippet.py"],
            cwd=str(scratch),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={
                "PATH": os.environ.get("PATH", ""),
                "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                "TEMP": str(scratch),
                "TMP": str(scratch),
            },
        )
        if handle and kernel32:
            process = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, started.pid)
            if process:
                kernel32.AssignProcessToJobObject(handle, process)
                kernel32.CloseHandle(process)
        try:
            out, err = started.communicate(timeout=seconds)
            timed_out = False
        except subprocess.TimeoutExpired:
            started.kill()
            out, err = started.communicate()
            timed_out = True
        made = sorted(
            one.name for one in scratch.iterdir() if one.is_file() and one.name != "snippet.py"
        )
        return {
            "exit_code": started.returncode,
            "stdout": (out or "")[:MAX_OUTPUT],
            "stderr": (err or "")[:MAX_OUTPUT],
            "timed_out": timed_out,
            "files_made": made,
            "limits": {
                "seconds": seconds,
                "memory_mb": memory // (1024 * 1024),
                "processes": PROCESS_LIMIT,
                "network": "blocked for ordinary use; not a security boundary",
            },
        }
    finally:
        if handle and kernel32:
            # Closing the handle kills anything still in the job.
            kernel32.CloseHandle(handle)
        shutil.rmtree(scratch, ignore_errors=True)


def register_sandbox_tools(registry: Any) -> None:
    from .tools import ToolSpec

    def code_run(code: str, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
        if not (code or "").strip():
            return {"error": "there is no code to run"}
        try:
            return run(code, timeout)
        except SandboxUnavailableError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # a broken sandbox is not a broken tool
            log.warning("the sandbox failed: %s", str(exc)[:200])
            return {"error": f"the sandbox could not run that: {str(exc)[:200]}"}

    registry.register(
        ToolSpec(
            name="code_run",
            description="Run a short Python snippet in a scratch directory, under limits.",
            arguments={"code": str},
            optional={"timeout": int},
            # Not gated: it cannot write to the workspace, cannot outlive its
            # timeout and cannot take the machine down. What it *can* do --
            # read files as the user -- is what `file_read` does unconfirmed
            # too, so a confirmation here would buy nothing and cost every use.
            sensitive=False,
            handler=code_run,
            describes={
                "code": "The whole snippet. It runs in its own empty directory with no "
                "arguments and no input; print what you want back.",
                "timeout": f"Seconds before it is killed. Default {DEFAULT_TIMEOUT}, "
                f"at most {MAX_TIMEOUT}.",
            },
        )
    )
