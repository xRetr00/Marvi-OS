"""Who this process is: Marvi's, which build, and since when.

Every long-lived thing Marvi starts -- the Gateway, the Agent, the room
sidecar, the wake listener, a browser host -- has to be identifiable by
anything that finds it later. Three different questions get asked about a
process holding a port or eating memory, and until now none of them had an
answer:

* **Is it mine?** A second checkout, or the Gateway an agent left running
  after a test in the repo, looks exactly like the real one from outside.
* **Is it this build?** Version cannot answer that. A version changes on
  release; a nightly's code changes every hour, so two processes built four
  hours apart report the same version, the check passes, and the stale one
  keeps serving with whatever was fixed in between. A check that can only
  fail on release day is not a check.
* **How long has it been there?** An hour-old process that stopped answering
  and a three-second-old one still starting need opposite treatment, and a
  PID tells you neither.

So the stamp carries all three, in a form a person can read in a log line:

    marvi.gateway.6e949353e928.20260910T091530Z.51008
    ^^^^^ ^^^^^^^ ^^^^^^^^^^^^ ^^^^^^^^^^^^^^^^ ^^^^^
    ours  what    which build  started when      pid

The leading `marvi` is deliberate and load-bearing. It is the cheapest
possible ownership test -- a substring match on a command line, a window
title, a file, a log -- and it is what lets a sweep decide whether a process
is even a candidate before doing anything more expensive.

This is an identity, not a secret. Anything on this machine could write one.
It answers "is that the same build as me", the way an ETag does, and nothing
about trust.
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

#: The first field of every stamp. Five characters, by design: it is the
#: ownership marker, and it has to be recognisable in text nobody formatted.
OURS = "marvi"

#: How much of the digest to show. Twelve hex characters is 48 bits -- far
#: past coincidence for the handful of builds that exist at once, and short
#: enough to read next to a PID.
SHOWN = 12

#: Field order in a stamp. Changing this breaks `parse` on older processes,
#: which is exactly the kind of silent mismatch the build digest exists to
#: catch, so `parse` is lenient about extra fields and strict about these.
SEPARATOR = "."

#: Set by a packaged build that knows its own identity, or by a test.
SETTING = "MARVI_BUILD_SIGNATURE"

#: Where a child is told its own stamp, so it can report it back.
STAMP_SETTING = "MARVI_PROCESS_STAMP"

#: When this process started. Read once: it is a fact about the process, and
#: a stamp whose time moved would defeat the point of carrying one.
_STARTED = time.time()


def _sources(root: Path) -> list[Path]:
    """Every Python file in the package, in a stable order.

    Sorted by *relative* path so two checkouts at different absolute paths
    produce the same digest. Otherwise `D:\\Marvi-OS` and the install copy of
    identical code would look like different builds -- the false positive
    that would make every launch kill a healthy Gateway.
    """
    return sorted(
        (p for p in root.rglob("*.py") if "__pycache__" not in p.parts),
        key=lambda p: p.relative_to(root).as_posix(),
    )


@lru_cache(maxsize=1)
def build() -> str:
    """This process's build signature. Stable for its lifetime.

    Cached deliberately: it describes the code *loaded*, which cannot change
    while running. Re-reading would let a process report a build it is not
    executing, which is worse than reporting none.
    """
    if said := os.environ.get(SETTING, "").strip():
        return said[:SHOWN]
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in _sources(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:  # pragma: no cover - a file vanishing mid-scan
            digest.update(b"?")
    return digest.hexdigest()[:SHOWN]


def when(started: float | None = None) -> str:
    """A start time that sorts, and that a person can read. `20260910T091530Z`."""
    moment = datetime.fromtimestamp(started or _STARTED, UTC)
    return moment.strftime("%Y%m%dT%H%M%SZ")


def stamp(kind: str, pid: int | None = None, started: float | None = None) -> str:
    """This process's full identity. See the module docstring for the shape."""
    clean = "".join(ch for ch in (kind or "process").lower() if ch.isalnum() or ch == "-")
    return SEPARATOR.join(
        (OURS, clean or "process", build(), when(started), str(pid or os.getpid()))
    )


def ours(text: str) -> bool:
    """Whether a string is one of Marvi's stamps.

    The cheap test, on purpose: it runs against command lines and log lines
    where the stamp is surrounded by other text.
    """
    return f"{OURS}{SEPARATOR}" in (text or "")


def parse(text: str) -> dict[str, object] | None:
    """Read a stamp back. None when it is not one of ours.

    Lenient about trailing fields and strict about the leading ones, so a
    later version that appends something is still readable by an older
    process rather than looking foreign to it.
    """
    if not ours(text):
        return None
    start = text.index(f"{OURS}{SEPARATOR}")
    fields = text[start:].split()[0].split(SEPARATOR)
    if len(fields) < 5:
        return None
    _, kind, digest, moment, pid, *_ = fields
    try:
        began = datetime.strptime(moment, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    return {
        "kind": kind,
        "build": digest,
        "started": began.isoformat(),
        "age_seconds": max(0.0, (datetime.now(UTC) - began).total_seconds()),
        "pid": int(pid) if pid.isdigit() else 0,
        "mine": digest == build(),
    }


def mine(other: str) -> bool:
    """Whether something out there is this same build.

    Takes a bare digest or a whole stamp, because callers have one or the
    other and making them normalise first is how one of them forgets.
    """
    if not other:
        return False
    if read := parse(other):
        return bool(read["mine"])
    return other.strip().lower() == build()


def describe(kind: str = "gateway") -> dict[str, object]:
    """What a process publishes so a caller can decide to attach or replace."""
    return {
        "stamp": stamp(kind),
        "build": build(),
        "pid": os.getpid(),
        "started": when(),
        "age_seconds": max(0.0, time.time() - _STARTED),
    }
