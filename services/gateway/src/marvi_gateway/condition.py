"""What the Gateway is doing, and why it is slow, in words rather than symptoms.

Everything that watches the Gateway watched it from outside: a health poll
either got an answer or did not, and "did not" became `Gateway unavailable` in
the status bar. That sentence is true of a crash, a restart, a busy loop and a
model loading, and those are four completely different situations for the
person looking at it.

The one that actually happened was the least alarming and the most confusing.
The embedding model loads on the first memory recall, and its first `encode`
takes about ten seconds -- during which the loop cannot answer anything, so
the desktop's two-second report timed out and the bar said the Gateway was
gone. It was not gone. It was busy, on the first turn, every time:

    13:45:34  could not report foreground voice session state
    13:45:47  Loading SentenceTransformer model from ...
    13:45:47  embeddings: BAAI/bge-small-en-v1.5 loaded on the CPU in 0.6s

Ten seconds of "unavailable" for something that was working exactly as
designed, and nothing anywhere said the word "embedding".

## What this is

A place for the Gateway to say what it is in the middle of, while it is in the
middle of it, so that anything asking gets a reason instead of a silence:

    with condition.doing("loading the memory embedding model"):
        ...

Whoever is answering health checks can then read `now()` and say *that*, and
whatever went slowly leaves a `Strain` behind that is worth mentioning out
loud -- to the person in a voice call through the agent, or to an empty room
through the announcer.

## What it is not

Not metrics, and not a log. Both of those exist and neither is readable by a
person standing in the kitchen. This holds one sentence at a time, in the
words Marvi would use to explain herself.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

#: Past this, being busy is worth explaining rather than just being busy.
#:
#: The desktop's own report gives up at two seconds, so anything longer is
#: already visible to somebody as a stall. One second of warning before that is
#: the difference between "it is thinking" and "it is broken".
WORTH_MENTIONING = 1.0

#: How long a finished strain stays worth talking about. Long enough for the
#: next health poll and the next turn to find it, short enough that Marvi is
#: not still apologising for a hiccup from ten minutes ago.
REMEMBERED_FOR = 120.0


@dataclass(frozen=True)
class Strain:
    """Something that took long enough to be worth explaining."""

    #: What she was doing, as she would say it: "loading the memory model".
    doing: str
    seconds: float
    at: float
    #: Set when the work failed rather than merely dragged.
    failed: str = ""

    def sentence(self) -> str:
        """One line a person can act on, or at least understand.

        Written to be read *and* spoken -- the announcer reads these -- so
        "took 1 seconds" is not acceptable output.
        """
        if self.failed:
            return f"{self.doing} failed: {self.failed}"
        whole = round(self.seconds)
        return f"{self.doing} took {whole} second{'' if whole == 1 else 's'}"


_lock = threading.Lock()
_doing: list[tuple[str, float]] = []
_last: Strain | None = None


@contextmanager
def doing(what: str) -> Iterator[None]:
    """Say what is happening for as long as it is happening.

    Nested calls are allowed and the innermost wins, because the innermost is
    the specific answer: "loading the memory embedding model" is more use than
    "answering a recall".
    """
    global _last, _spoken
    began = time.monotonic()
    with _lock:
        _doing.append((what, began))
    failed = ""
    try:
        yield
    except Exception as exc:
        failed = str(exc)[:200]
        raise
    finally:
        spent = time.monotonic() - began
        with _lock:
            for index in range(len(_doing) - 1, -1, -1):
                if _doing[index] == (what, began):
                    del _doing[index]
                    break
            if failed or spent >= WORTH_MENTIONING:
                _last = Strain(doing=what, seconds=spent, at=time.time(), failed=failed)
                _spoken = False


def now() -> str:
    """What the Gateway is in the middle of, or empty if it is idle.

    The innermost of anything nested: the most specific answer is the useful
    one.
    """
    with _lock:
        return _doing[-1][0] if _doing else ""


def dragging(threshold: float = WORTH_MENTIONING) -> str:
    """What has been going on long enough that somebody has noticed.

    Empty while the Gateway is merely busy. This is the one a status line
    should read: it fills in exactly when a person starts wondering.
    """
    with _lock:
        if not _doing:
            return ""
        what, began = _doing[-1]
    return what if time.monotonic() - began >= threshold else ""


def recent(now_at: float | None = None) -> Strain | None:
    """The last thing that dragged or failed, while it is still relevant."""
    with _lock:
        strain = _last
    if strain is None:
        return None
    moment = time.time() if now_at is None else now_at
    return strain if moment - strain.at <= REMEMBERED_FOR else None


#: Whether the last strain has already been said out loud.
_spoken = False


def worth_saying(name: str = "") -> str:
    """A line about the last strain, once, or empty.

    The Gateway decides whether there is anything to mention and how to say
    it; whoever is carrying it just carries it. Marked as said on the way out,
    because the failure this avoids is Marvi telling you about the same
    ten-second pause at the start of every turn for the next two minutes.
    """
    global _spoken
    with _lock:
        strain, already = _last, _spoken
    if strain is None or already:
        return ""
    from . import voicing

    line = voicing.spoken(
        {
            "source": "system",
            # A failure and a slow patch are different news and want different
            # words: "which is why I was slow" is the wrong register for
            # something that did not work at all.
            "kind": "failed" if strain.failed else "slow",
            "summary": strain.sentence(),
            "at": strain.at,
            "payload": {
                "doing": strain.doing,
                "seconds": strain.seconds,
                "why": strain.failed,
            },
        },
        name,
    )
    if not line:
        return ""
    with _lock:
        _spoken = True
    return line


def forget() -> None:
    """Drop what is remembered. For tests, and after it has been said."""
    global _last, _spoken
    with _lock:
        _last = None
        _spoken = False
        _doing.clear()


def note(what: str, seconds: float, failed: str = "", regardless: bool = False) -> None:
    """Record something that already happened and took too long.

    The counterpart to `doing`. `doing` is for the few places worth naming
    from the inside; this is for instrumentation that watches everything from
    the outside and does not know what it is looking at until afterwards. See
    `watchdog`, which is the general answer -- wrapping suspects one at a time
    only ever catches the ones already under suspicion.
    """
    global _last, _spoken
    # `regardless` is for a caller whose own threshold has already decided.
    # A blocked event loop is the case: `watchdog.BLOCKED` is a quarter of a
    # second because the loop stopping at all is notable, and measuring it as
    # overshoot from a one-second heartbeat under-reports a block that began
    # mid-interval -- so a real stall can arrive here looking small.
    if not failed and not regardless and seconds < WORTH_MENTIONING:
        return
    with _lock:
        _last = Strain(doing=what, seconds=seconds, at=time.time(), failed=failed)
        _spoken = False


def as_dict() -> dict[str, Any]:
    """For the runtime status, so a stall can name itself."""
    strain = recent()
    return {
        "doing": now(),
        "dragging": dragging(),
        "recent": strain.sentence() if strain else "",
    }
