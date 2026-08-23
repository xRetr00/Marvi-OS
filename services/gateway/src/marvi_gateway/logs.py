"""The logging engine.

The bug that started Phase 10 was three services dying with the reason going
nowhere. So the requirement here is not "add some logging" — it is **nothing is
lost**. Everything this module does follows from that.

## Nothing is lost

Python drops things on the floor in more ways than one file handler catches, so
all of them are claimed:

* **Library loggers.** `httpx`, `uvicorn`, and `apscheduler`
  friends log to their own names. They are routed to a subsystem rather than
  ignored — a connection error from `httpx` is usually the most useful line in
  the file.
* **Uncaught exceptions**, on the main thread and on every other thread.
  `sys.excepthook` only covers the main one; `threading.excepthook` is the rest,
  and a crashed background thread is exactly the failure nobody notices.
* **Unraisable exceptions** — errors inside `__del__` and garbage collection,
  which normally print to stderr and vanish.
* **asyncio**'s exception handler, which otherwise reports "task exception was
  never retrieved" to a stderr nobody is reading.
* **Warnings**, including deprecations that predict the next breakage.

## Nothing blocks

A log write on the voice path must never add latency, so handlers sit behind a
`QueueListener`. The calling thread does a queue put; a background thread does
the file I/O. This is also what makes logging safe from inside the audio
callback.

## Nothing leaks

Redaction is **value-based, not pattern-based**. Marvi knows its own secrets —
they are in the environment — so the filter scrubs those exact strings wherever
they appear, in any field, from any library, including one that logs a full URL
with a key in the query string. Pattern matching is kept as a second layer for
tokens Marvi has not seen, but the primary defence does not depend on guessing a
format.

## Adding a subsystem is one line

`get_logger("newthing")` creates `newthing.log` on first use. No registry to
update, no handler to wire. Routing for a module is a single entry in
`MODULE_SUBSYSTEMS`, and an unmapped module lands in `gateway.log` rather than
being dropped.
"""

from __future__ import annotations

import atexit
import contextlib
import copy
import logging
import logging.handlers
import os
import queue
import re
import sys
import threading
import warnings
from pathlib import Path
from typing import Any, TextIO

# Per-subsystem files. `errors.log` is not in this list because it is a fan-in
# of every other file rather than a subsystem of its own.
ERROR_FILE = "errors.log"

DEFAULT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_BACKUPS = 3
# The error file keeps more history: it is small, and it is the one people read.
ERROR_MAX_BYTES = 4 * 1024 * 1024
ERROR_BACKUPS = 5

# Which file a module's logger goes to. Prefix match, longest first, so
# `marvi_gateway.providers.oauth` finds `providers` before `marvi_gateway`.
MODULE_SUBSYSTEMS: dict[str, str] = {
    "marvi_gateway.providers": "providers",
    "marvi_gateway.deliberate": "mind",
    "marvi_gateway.initiative": "mind",
    "marvi_gateway.mind": "mind",
    "marvi_gateway.policy": "mind",
    "marvi_gateway.journal": "mind",
    "marvi_gateway.memory": "memory",
    "marvi_gateway.chat": "chat",
    "marvi_gateway.room": "room",
    "marvi_gateway.announce": "voice",
    "marvi_gateway.setup": "setup",
    "marvi_gateway.doctor": "doctor",
    "marvi_agent": "voice",
    # Libraries. Losing these is losing the actual cause most of the time.
    "httpx": "providers",
    "httpcore": "providers",
    "openai": "providers",
    "anthropic": "providers",
    "uvicorn": "gateway",
    "fastapi": "gateway",
    "apscheduler": "mind",
    "livekit": "voice",
    "composio": "gateway",
    "mcp": "gateway",
}

FALLBACK_SUBSYSTEM = "gateway"

# Second-layer redaction for shapes Marvi has not been handed. The first layer
# (known values) does the real work; these catch a token from a library that
# Marvi never stored.
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"(?i)\b(authorization|x-api-key)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}"),
    # A key in a query string is the classic accidental disclosure.
    re.compile(r"(?i)([?&](?:api_?key|access_token|token|key)=)[^&\s]+"),
)

REDACTED = "[redacted]"

# Names whose *values* are secrets. Matches providers/config.py so the two
# cannot disagree about what counts as sensitive.
SECRET_NAME_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL")
# Short values are not worth scrubbing and would mangle ordinary text: a
# two-character "key" would blank out every occurrence of those characters.
MIN_SECRET_LENGTH = 8


def logs_dir() -> Path:
    from .paths import logs_dir as resolved

    return resolved()


def subsystem_for(logger_name: str) -> str:
    """Which file this logger's records belong in."""
    best = ""
    for prefix in MODULE_SUBSYSTEMS:
        if (logger_name == prefix or logger_name.startswith(prefix + ".")) and len(
            prefix
        ) > len(best):
            best = prefix
    return MODULE_SUBSYSTEMS[best] if best else FALLBACK_SUBSYSTEM


# -- redaction ---------------------------------------------------------------


class Redactor:
    """Removes known secret values from anything on its way to disk.

    Value-based first: Marvi holds its own credentials, so it can scrub those
    exact strings from any field written by any library. That works on a URL
    with a key in the query string, a repr of a headers dict, and a traceback
    line — places a field-name-based filter would never look.
    """

    def __init__(self) -> None:
        self._values: tuple[str, ...] = ()
        self._lock = threading.Lock()
        self.refresh()

    def refresh(self) -> None:
        """Re-read the environment. Call after provider settings change."""
        found: set[str] = set()
        for name, value in os.environ.items():
            if not any(marker in name.upper() for marker in SECRET_NAME_MARKERS):
                continue
            cleaned = (value or "").strip()
            if len(cleaned) >= MIN_SECRET_LENGTH:
                found.add(cleaned)
        with self._lock:
            # Longest first: a token that contains another token as a prefix
            # must not be half-scrubbed and left recognisable.
            self._values = tuple(sorted(found, key=len, reverse=True))

    def add(self, secret: str) -> None:
        """Register a secret that never went through the environment.

        OAuth access tokens arrive over HTTP and are stored encrypted; they are
        never environment variables, so nothing else would ever know to hide
        them.
        """
        cleaned = (secret or "").strip()
        if len(cleaned) < MIN_SECRET_LENGTH:
            return
        with self._lock:
            self._values = tuple(
                sorted({*self._values, cleaned}, key=len, reverse=True)
            )

    def scrub(self, text: str) -> str:
        with self._lock:
            values = self._values
        for secret in values:
            if secret in text:
                text = text.replace(secret, REDACTED)
        for pattern in SECRET_PATTERNS:
            text = pattern.sub(
                lambda m: (m.group(1) + REDACTED) if m.groups() else REDACTED, text
            )
        return text


_redactor = Redactor()


def redactor() -> Redactor:
    return _redactor


class RedactionFilter(logging.Filter):
    """Applied to every handler, not to a logger.

    On a handler it cannot be bypassed by a library that logs through its own
    logger, which is exactly the case that matters.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Render now, so args and lazy %-formatting are scrubbed too. A
            # secret passed as an argument is still a secret.
            rendered = record.getMessage()
        except Exception:
            # A bad __str__ in a logged object must never reach the caller.
            rendered = str(record.msg)
        record.msg = _redactor.scrub(rendered)
        record.args = ()

        # Render the traceback here rather than leaving it to the formatter.
        # The formatter runs *after* this filter, so an exception rendered
        # there would never be scrubbed — and a secret in a traceback is the
        # most likely way one reaches disk.
        if record.exc_info and not record.exc_text:
            try:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            except Exception:
                record.exc_text = "<traceback unavailable>"
        if record.exc_text:
            record.exc_text = _redactor.scrub(record.exc_text)
        if record.stack_info:
            record.stack_info = _redactor.scrub(record.stack_info)
        for key, value in list(record.__dict__.items()):
            if key.startswith("marvi_") and isinstance(value, str):
                record.__dict__[key] = _redactor.scrub(value)
        return True


# -- formatting --------------------------------------------------------------


_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class MarviFormatter(logging.Formatter):
    """Readable first, parseable second.

    A user pastes this into a bug report, so it has to read like text. Trailing
    `key=value` pairs keep it machine-readable without a second format — the
    same line serves a person and a script.
    """

    default_time_format = "%Y-%m-%d %H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"{self.formatTime(record)} {record.levelname:<7} "
            f"[{subsystem_for(record.name)}] {record.name} — {record.getMessage()}"
        )
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED and not key.startswith("_")
        }
        if extras:
            rendered = " ".join(f"{k}={v!r}" for k, v in sorted(extras.items()))
            base = f"{base} | {rendered}"
        # Prefer the pre-rendered text. The redaction filter renders and scrubs
        # the traceback precisely so this line cannot write a raw one — a
        # secret in a traceback is the likeliest way one reaches disk.
        rendered_exception = record.exc_text or (
            self.formatException(record.exc_info) if record.exc_info else ""
        )
        if rendered_exception:
            base = f"{base}\n{rendered_exception}"
        if record.stack_info:
            base = f"{base}\n{record.stack_info}"
        return base


class _PassthroughQueue(logging.handlers.QueueHandler):
    """Enqueue the record itself, not a pre-formatted copy.

    The stock `QueueHandler` calls `format()` in `prepare()` so the record can
    cross a process boundary. Here the listener is a thread in the same
    process, so that costs the real `exc_info`, the extras, and — worst — it
    formats the message *before* the redaction filter on the sink handlers ever
    sees it.

    It is still copied rather than passed by reference. Another handler on the
    root logger formatting the same record would otherwise mutate the object
    already sitting in the queue, and a traceback rendered by somebody else is
    a traceback the redaction filter never had a chance to scrub.
    """

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        return copy.copy(record)


class SubsystemRouter(logging.Handler):
    """One handler that writes each record to its subsystem's own file.

    A handler per subsystem attached to a logger each would mean knowing every
    subsystem up front. Routing at emit time is what makes `get_logger("new")`
    work with no registration.
    """

    def __init__(self, directory: Path, max_bytes: int, backups: int) -> None:
        super().__init__()
        self.directory = directory
        self.max_bytes = max_bytes
        self.backups = backups
        self._files: dict[str, logging.Handler] = {}
        self._lock_files = threading.Lock()

    def _handler_for(self, subsystem: str) -> logging.Handler:
        existing = self._files.get(subsystem)
        if existing is not None:
            return existing
        with self._lock_files:
            existing = self._files.get(subsystem)
            if existing is not None:
                return existing
            handler = logging.handlers.RotatingFileHandler(
                self.directory / f"{subsystem}.log",
                maxBytes=self.max_bytes,
                backupCount=self.backups,
                encoding="utf-8",
                delay=True,
            )
            handler.setFormatter(self.formatter)
            self._files[subsystem] = handler
            return handler

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._handler_for(subsystem_for(record.name)).emit(record)
        except Exception:
            # A logging failure must never become the application's failure.
            self.handleError(record)

    def close(self) -> None:
        with self._lock_files:
            for handler in self._files.values():
                handler.close()
            self._files.clear()
        super().close()


# -- setup -------------------------------------------------------------------

_configured = False
_listener: logging.handlers.QueueListener | None = None
_lock = threading.Lock()


def configure(
    directory: Path | None = None,
    level: str | None = None,
    console: bool = True,
) -> Path:
    """Install the engine. Idempotent; safe to call from every entry point."""
    global _configured, _listener
    with _lock:
        if _configured:
            return logs_dir()

        target = directory or logs_dir()
        target.mkdir(parents=True, exist_ok=True)
        chosen = (level or os.environ.get("MARVI_LOG_LEVEL", "INFO")).upper()
        formatter = MarviFormatter()
        redaction = RedactionFilter()

        router = SubsystemRouter(
            target,
            int(os.environ.get("MARVI_LOG_MAX_BYTES", DEFAULT_MAX_BYTES)),
            int(os.environ.get("MARVI_LOG_BACKUPS", DEFAULT_BACKUPS)),
        )
        router.setFormatter(formatter)
        router.addFilter(redaction)

        # The fan-in. This is the file people actually open, so it collects
        # every warning and error from every subsystem in one timeline.
        errors = logging.handlers.RotatingFileHandler(
            target / ERROR_FILE,
            maxBytes=ERROR_MAX_BYTES,
            backupCount=ERROR_BACKUPS,
            encoding="utf-8",
            delay=True,
        )
        errors.setLevel(logging.WARNING)
        errors.setFormatter(formatter)
        errors.addFilter(redaction)

        sinks: list[logging.Handler] = [router, errors]
        if console:
            # The Windows console is not UTF-8 by default, and an em dash in
            # the format would otherwise render as a replacement character or
            # raise. Files are always UTF-8; only the terminal needs this.
            with contextlib.suppress(AttributeError, OSError):
                sys.stderr.reconfigure(errors="replace")  # type: ignore[union-attr]
            stream = logging.StreamHandler()
            stream.setFormatter(formatter)
            stream.addFilter(redaction)
            sinks.append(stream)

        # Everything goes through a queue so no caller ever waits on disk. The
        # voice path logs from latency-critical code.
        records: queue.SimpleQueue[Any] = queue.SimpleQueue()
        root = logging.getLogger()
        root.setLevel(getattr(logging, chosen, logging.INFO))
        for handler in list(root.handlers):
            root.removeHandler(handler)
        root.addHandler(_PassthroughQueue(records))

        _listener = logging.handlers.QueueListener(
            records, *sinks, respect_handler_level=True
        )
        _listener.start()

        _install_catchers()
        atexit.register(shutdown)
        _configured = True

        logging.getLogger("marvi_gateway.logs").info(
            "logging started", extra={"marvi_dir": str(target), "marvi_level": chosen}
        )
        return target


def shutdown() -> None:
    global _configured, _listener
    with _lock:
        if _listener is not None:
            _listener.stop()
            _listener = None
        _configured = False


def get_logger(subsystem: str) -> logging.Logger:
    """A logger for a named subsystem; its file appears on first write."""
    if subsystem in MODULE_SUBSYSTEMS.values() or subsystem == FALLBACK_SUBSYSTEM:
        return logging.getLogger(f"marvi.{subsystem}")
    # Unknown name: register it so routing finds it, then hand it back. This is
    # the whole of "adding a subsystem".
    MODULE_SUBSYSTEMS[f"marvi.{subsystem}"] = subsystem
    return logging.getLogger(f"marvi.{subsystem}")


# -- catching what would otherwise be lost ------------------------------------


def _install_catchers() -> None:
    engine = logging.getLogger("marvi_gateway.logs")

    def on_exception(kind, value, traceback) -> None:  # type: ignore[no-untyped-def]
        if issubclass(kind, KeyboardInterrupt):
            sys.__excepthook__(kind, value, traceback)
            return
        engine.critical("uncaught exception", exc_info=(kind, value, traceback))

    sys.excepthook = on_exception

    def on_thread_exception(args) -> None:  # type: ignore[no-untyped-def]
        # A background thread dying quietly is the failure nobody notices.
        engine.critical(
            "uncaught exception in thread %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = on_thread_exception

    def on_unraisable(args) -> None:  # type: ignore[no-untyped-def]
        # Errors in __del__ and during collection; normally printed and lost.
        engine.error(
            "unraisable exception in %r",
            getattr(args, "object", None),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.unraisablehook = on_unraisable

    def on_warning(  # type: ignore[no-untyped-def]
        message, category, filename, lineno, file: TextIO | None = None, line=None
    ) -> None:
        engine.warning(
            "%s: %s", getattr(category, "__name__", category), message,
            extra={"marvi_where": f"{filename}:{lineno}"},
        )

    warnings.showwarning = on_warning


def is_client_hangup(context: dict[str, Any]) -> bool:
    """Is this asyncio complaining about a client that closed abruptly?

    On Windows a client dropping a connection makes the proactor transport
    raise `ConnectionResetError` (WinError 10054) from
    `_ProactorBasePipeTransport._call_connection_lost`, and asyncio hands it to
    the exception handler. Nothing is wrong: an HTTP client is allowed to hang
    up, and the Electron shell does it routinely as it abandons poll requests.

    Logged as an error it produced 388 entries in one session of `errors.log`,
    which is how a healthy Gateway came to look like a crashing one. So it is
    recognised and dropped to debug — recognised specifically, because a
    connection reset from somewhere that is *not* a transport teardown is a
    real event and must keep its level.
    """
    exception = context.get("exception")
    if not isinstance(exception, ConnectionResetError):
        return False
    message = str(context.get("message", ""))
    return "_call_connection_lost" in message or "connection_lost" in message


def install_asyncio_handler(loop: Any) -> None:
    """Route asyncio's own errors into the engine.

    Separate because it needs a running loop. Without it, "task exception was
    never retrieved" goes to a stderr nobody reads.
    """
    engine = logging.getLogger("marvi_gateway.logs")

    def handler(_loop: Any, context: dict[str, Any]) -> None:
        exception = context.get("exception")
        level = logging.DEBUG if is_client_hangup(context) else logging.ERROR
        engine.log(
            level,
            "asyncio: %s", context.get("message", "unhandled error"),
            exc_info=exception if (exception and level >= logging.ERROR) else None,
        )

    loop.set_exception_handler(handler)


# -- reading ------------------------------------------------------------------


def available(directory: Path | None = None) -> list[str]:
    target = directory or logs_dir()
    try:
        return sorted(path.stem for path in target.glob("*.log"))
    except OSError:
        return []


def tail(subsystem: str, lines: int = 200, directory: Path | None = None) -> list[str]:
    """Last lines of one subsystem's file, for the Doctor page and the CLI."""
    target = (directory or logs_dir()) / f"{subsystem}.log"
    try:
        # Read the tail rather than the whole file: these rotate at 8 MB and
        # the Doctor page must not stall on one.
        with target.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            window = min(size, max(4096, lines * 400))
            handle.seek(size - window)
            content = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return content.splitlines()[-lines:]


def ingest(subsystem: str, line: str, level: int = logging.INFO) -> None:
    """Record a line produced by another process.

    The Electron shell and the supervised services write their own stdout; this
    is how that output joins the same timeline instead of living in a separate
    world.
    """
    logging.getLogger(f"marvi.{subsystem}").log(level, "%s", line.rstrip())
    MODULE_SUBSYSTEMS.setdefault(f"marvi.{subsystem}", subsystem)
