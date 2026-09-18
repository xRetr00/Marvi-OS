"""An AppContainer: the part of the sandbox that is actually a boundary.

The Job Object in `sandbox.py` caps what a snippet can *spend* -- memory, time,
processes. It does not cap what a snippet can *reach*, and the module says so.
This is the other half: a process running under a **lowbox token**, which is
the only thing on Windows that makes "it cannot read your documents" true
rather than polite.

## What the OS enforces, and why it is not a guard in the interpreter

An AppContainer process gets a token whose SID is the container's. A file is
reachable only if its DACL names that SID, or `ALL APPLICATION PACKAGES`, and
almost nothing outside `System32` does. So `%USERPROFILE%` is unreadable -- not
because a wrapper intercepted `open()`, which `ctypes` would walk straight past,
but because the kernel refuses the handle.

The same token carries **no capabilities**. `internetClient` is the one that
buys network access and it is not granted, so Windows Firewall drops the
connection before it leaves the process. A snippet that calls `socket` directly,
through `ctypes`, or by spawning something else, gets nothing.

## What has to be granted, and the honest failure

Two things must name the container SID or the interpreter will not start:

- the **scratch directory**, full control, so the snippet has somewhere to be;
- the **Python installation**, read and execute, so there is an interpreter.

The second is a lasting change to a directory's permissions, so it is made
once, narrowly (read and execute, nothing else), only to a SID Marvi created,
and it is logged when it happens. It also **fails for a system-wide Python**:
changing a DACL under `C:\\Program Files` needs rights an ordinary user does not
have, and Marvi does not ask for them. When it fails, `available()` says no and
`sandbox.run` falls back to the Job Object alone and *reports which one ran*.
A sandbox that silently stops being a boundary is worse than one that never was.

Switch it off with `MARVI_SANDBOX_APPCONTAINER=0`.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes
from pathlib import Path
from typing import Any

from .logs import get_logger

log = get_logger("gateway")

SETTING = "MARVI_SANDBOX_APPCONTAINER"

#: The container Marvi creates. One, reused: a profile per call would leave a
#: trail of them in the user's registry.
CONTAINER_NAME = "MarviOS.CodeSandbox"
CONTAINER_DISPLAY = "Marvi OS code sandbox"
CONTAINER_ABOUT = "Runs snippets from code_run with no capabilities."

ERROR_ALREADY_EXISTS = 0x800700B7

EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
STARTF_USESTDHANDLES = 0x00000100
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009

GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
CREATE_ALWAYS = 2
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE = wintypes.HANDLE(-1).value
WAIT_TIMEOUT = 0x00000102


class LowboxUnavailableError(Exception):
    """This machine cannot give us a container, and said why."""


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _SecurityCapabilities(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.POINTER(_SidAndAttributes)),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class _StartupInfoW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _StartupInfoExW(ctypes.Structure):
    _fields_ = [("StartupInfo", _StartupInfoW), ("lpAttributeList", ctypes.c_void_p)]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


def wanted() -> bool:
    """Whether the owner has left the container on. It is on by default."""
    return (os.environ.get(SETTING, "1") or "1").strip().lower() not in {"0", "off", "false", "no"}


def _sid() -> tuple[ctypes.c_void_p, str]:
    """The container's SID, creating the profile the first time. `(sid, text)`."""
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    sid = ctypes.c_void_p()
    made = userenv.CreateAppContainerProfile(
        ctypes.c_wchar_p(CONTAINER_NAME),
        ctypes.c_wchar_p(CONTAINER_DISPLAY),
        ctypes.c_wchar_p(CONTAINER_ABOUT),
        None,
        0,
        ctypes.byref(sid),
    )
    # The profile outlives the process, so the ordinary case after the first
    # run is "already exists" -- which is success, not failure.
    if (made & 0xFFFFFFFF) == ERROR_ALREADY_EXISTS:
        got = userenv.DeriveAppContainerSidFromAppContainerName(
            ctypes.c_wchar_p(CONTAINER_NAME), ctypes.byref(sid)
        )
        if got != 0:
            raise LowboxUnavailableError(f"Windows would not name the container (0x{got & 0xFFFFFFFF:08x})")
    elif made != 0:
        raise LowboxUnavailableError(f"Windows would not create the container (0x{made & 0xFFFFFFFF:08x})")

    text = ctypes.c_wchar_p()
    if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        raise LowboxUnavailableError("Windows would not write the container's SID out")
    written = str(text.value)
    ctypes.WinDLL("kernel32").LocalFree(text)
    return sid, written


def _icacls(arguments: list[str], why: str) -> bool:
    """One `icacls` run. False, with the reason logged, if Windows said no."""
    done = subprocess.run(
        ["icacls", *arguments], capture_output=True, text=True, timeout=180, check=False
    )
    if done.returncode != 0:
        log.info("the sandbox could not %s: %s", why, (done.stderr or done.stdout or "").strip()[:200])
    return done.returncode == 0


def _grant(path: Path, sid_text: str, rights: str, existing: bool = False) -> bool:
    """Name the container in a directory's permissions. True if it took.

    `icacls` rather than `SetEntriesInAcl`: the same operation in one line a
    person can read, run by hand, and undo.

    `existing` is for a directory that already has files in it, and it costs a
    second pass for a reason worth writing down. `(OI)(CI)` are *container*
    inheritance flags; `icacls /T` silently drops an ACE carrying them when it
    reaches a file, so the one command that looks like it does both does
    neither. Measured on this machine: the interpreter's directory took the
    inheritable ACE, every file under it took nothing, and the container then
    failed to start with `permission denied (os error 5)` -- from the loader,
    not from Python, which is the confusing kind of failure.

    So: the inheritable ACE on the directory, for files that arrive later, and
    a plain one walked over the files that are already there.
    """
    if not _icacls(
        [str(path), "/grant", f"*{sid_text}:(OI)(CI){rights}", "/Q"],
        f"be given {rights} on {path}",
    ):
        return False
    if not existing:
        return True
    # `/C` so one unreadable file does not fail the whole tree. ~1.6s for the
    # 3,800 files of a CPython installation, once.
    return _icacls(
        [str(path), "/grant", f"*{sid_text}:{rights}", "/T", "/C", "/Q"],
        f"be given {rights} on what is already inside {path}",
    )


#: What the child is told, beyond its own scratch paths.
#:
#: The profile variables are not a convenience: **without them CreateProcessW
#: refuses the container with `ERROR_ENVVAR_NOT_FOUND` (203)**, because it
#: redirects each of these into the container's own per-package folder and has
#: to read the original to do it. A minimal block gets you 203 and no clue.
#:
#: Their *values* are paths the snippet cannot open anyway -- that is the whole
#: point of the container -- so what leaks is the shape of a home directory,
#: not its contents.
_NEEDED = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "USERPROFILE", "APPDATA",
           "LOCALAPPDATA", "ALLUSERSPROFILE", "PROGRAMDATA")


def _environment(scratch: Path) -> ctypes.Array:
    """A `CREATE_UNICODE_ENVIRONMENT` block: `K=V\\0K=V\\0\\0`."""
    values = {name: os.environ[name] for name in _NEEDED if os.environ.get(name)}
    values["TEMP"] = values["TMP"] = str(scratch)
    joined = "".join(
        f"{key}={value}\0" for key, value in sorted(values.items(), key=lambda kv: kv[0].upper())
    ) + "\0"
    return ctypes.create_unicode_buffer(joined)


def available(python: Path) -> tuple[bool, str]:
    """Whether a container can actually run this interpreter, and why not.

    Asks by doing: the grants are what fails on a machine where this cannot
    work, so there is no point pretending a cheaper check means anything.
    """
    if os.name != "nt":
        return False, "AppContainers are a Windows thing"
    if not wanted():
        return False, f"{SETTING} is off"
    try:
        sid, text = _sid()
    except (LowboxUnavailableError, OSError, AttributeError) as exc:
        return False, str(exc)
    try:
        for root in _interpreter_roots(python):
            if not _grant(root, text, "(RX)", existing=True):
                return False, (
                    f"Windows would not let Marvi grant read access on {root} -- a Python "
                    "installed for every user needs an administrator to do that once"
                )
    finally:
        ctypes.WinDLL("advapi32").FreeSid(sid)
    return True, ""


def _interpreter_roots(python: Path) -> list[Path]:
    """The directories an interpreter needs to be readable to start.

    Both prefixes, because a virtual environment's `python.exe` is a stub that
    loads the real installation's DLL and standard library.
    """
    import sys

    roots = {Path(sys.prefix), Path(sys.base_prefix), Path(python).parent.parent}
    return [root for root in sorted(roots) if root.exists()]


def run(
    python: Path,
    arguments: list[str],
    scratch: Path,
    timeout: int,
    job: Any = None,
) -> dict[str, Any]:
    """Run a command in the container, with output going to files in `scratch`.

    Files rather than pipes: the child writes through inherited handles, so
    there is no reader to deadlock and nothing to drain on a timeout -- and a
    process being killed mid-write still leaves what it had already printed.

    Started suspended and resumed only after it is in the job, so a snippet
    cannot spend anything before the limits apply.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    sid, text = _sid()
    handles: list[Any] = []
    attributes = None
    try:
        if not _grant(scratch, text, "(F)"):
            raise LowboxUnavailableError("the container could not be given its own scratch directory")

        inheritable = _SecurityAttributes()
        inheritable.nLength = ctypes.sizeof(inheritable)
        inheritable.bInheritHandle = True

        def _open(name: str) -> wintypes.HANDLE:
            handle = kernel32.CreateFileW(
                ctypes.c_wchar_p(str(scratch / name)), GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE, ctypes.byref(inheritable),
                CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, None,
            )
            if handle == INVALID_HANDLE:
                raise LowboxUnavailableError(f"could not open {name} for the snippet's output")
            handles.append(handle)
            return handle

        out_handle, err_handle = _open("stdout.txt"), _open("stderr.txt")

        size = ctypes.c_size_t(0)
        kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attributes = ctypes.create_string_buffer(size.value)
        if not kernel32.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)):
            raise LowboxUnavailableError("Windows refused the process attribute list")

        capabilities = _SecurityCapabilities()
        capabilities.AppContainerSid = sid
        # None. `internetClient` is the one that would buy network access, and
        # the whole point of this is that a snippet does not get it.
        capabilities.Capabilities = None
        capabilities.CapabilityCount = 0
        if not kernel32.UpdateProcThreadAttribute(
            attributes, 0, ctypes.c_size_t(PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES),
            ctypes.byref(capabilities), ctypes.sizeof(capabilities), None, None,
        ):
            raise LowboxUnavailableError("Windows refused the container attribute")

        started = _StartupInfoExW()
        started.StartupInfo.cb = ctypes.sizeof(started)
        started.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        started.StartupInfo.hStdInput = None
        started.StartupInfo.hStdOutput = out_handle
        started.StartupInfo.hStdError = err_handle
        started.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)

        information = _ProcessInformation()
        command = subprocess.list2cmdline([str(python), *arguments])
        if not kernel32.CreateProcessW(
            ctypes.c_wchar_p(str(python)),
            ctypes.create_unicode_buffer(command),
            None, None, True,
            EXTENDED_STARTUPINFO_PRESENT
            | CREATE_SUSPENDED
            | CREATE_UNICODE_ENVIRONMENT
            | CREATE_NO_WINDOW,
            _environment(scratch),
            ctypes.c_wchar_p(str(scratch)),
            ctypes.byref(started),
            ctypes.byref(information),
        ):
            raise LowboxUnavailableError(
                f"Windows would not start the interpreter in the container "
                f"(error {ctypes.get_last_error()})"
            )

        try:
            if job:
                kernel32.AssignProcessToJobObject(job, information.hProcess)
            kernel32.ResumeThread(information.hThread)
            waited = kernel32.WaitForSingleObject(information.hProcess, timeout * 1000)
            timed_out = waited == WAIT_TIMEOUT
            if timed_out:
                kernel32.TerminateProcess(information.hProcess, 1)
                kernel32.WaitForSingleObject(information.hProcess, 5000)
            code = wintypes.DWORD(0)
            kernel32.GetExitCodeProcess(information.hProcess, ctypes.byref(code))
        finally:
            kernel32.CloseHandle(information.hThread)
            kernel32.CloseHandle(information.hProcess)

        # Closed before reading: the child's handles are gone with it, and ours
        # are what is holding the files open.
        for handle in handles:
            kernel32.CloseHandle(handle)
        handles.clear()
        return {
            "exit_code": 1 if timed_out else int(code.value),
            "stdout": _read(scratch / "stdout.txt"),
            "stderr": _without_launcher_noise(_read(scratch / "stderr.txt")),
            "timed_out": timed_out,
        }
    finally:
        for handle in handles:
            kernel32.CloseHandle(handle)
        if attributes is not None:
            kernel32.DeleteProcThreadAttributeList(attributes)
        advapi32.FreeSid(sid)


#: A line the launcher writes, not the snippet.
#:
#: A `python.exe` inside a virtual environment built by `uv` is a trampoline
#: that finds the real interpreter and runs it. Inside the container it cannot
#: read its own image path back, says so on stderr, falls back, and works. The
#: snippet is fine and its own stderr is untouched -- but a line about a file
#: nobody mentioned, on every single successful run, reads like a failure.
#:
#: Removed by exact prefix and only at the start, so a snippet that prints
#: these words itself still gets them back.
_LAUNCHER_NOISE = "Failed to find real location of "


def _without_launcher_noise(text: str) -> str:
    kept = [
        line for line in text.splitlines(keepends=True)
        if not line.startswith(_LAUNCHER_NOISE)
    ]
    return "".join(kept)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
