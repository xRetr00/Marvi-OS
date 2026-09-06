"""Things worth saying that could not be said yet.

Every rule in `policy` that stops Marvi speaking is a rule about *now*. She is
in a call, you are out, it is half past two in the morning, the day's thinking
budget is gone, a model is rate limited. Each of those is a reason to not speak
this second and none of them is a reason to never speak -- and until now they
were the same thing, because a downgraded verdict left the event in the journal
and moved on.

So the thing that mattered was lost precisely when it mattered most:

    Your three Google mailboxes are deactivated over an unpaid renewal, and
    deletion is on hold.

arriving at 03:10, downgraded for quiet hours, and never mentioned again --
while the mail itself said the mailboxes would be deleted by the end of the
day.

This is the waiting room. Something that was worth saying is held with the
reason it could not be said, and offered again when that reason has passed.

## Why the reason is kept

Because it is most of what makes the eventual line not weird. "Your mailboxes
are being deleted" said six hours late is alarming; "while you were out, your
mailboxes were being deleted" is an assistant that waited for you. The delay
is only strange when it goes unexplained.

## Why it expires

A thing worth interrupting for this morning is not worth interrupting for
tomorrow, and a queue that never drops anything eventually reads its own
history at you. Twelve hours, then it is only a memory and the journal already
has it.

## Why it is on disk

The commonest reason to be holding something is that nobody is home, and the
second commonest is that the machine is off. A waiting room that empties on
restart would forget exactly the cases it exists for.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .logs import get_logger

log = get_logger("mind")

#: Verdict reasons that will pass on their own, and how Marvi explains the
#: delay afterwards. A reason that is not here is not queued -- `initiative
#: -paused` means the user switched her off, and holding a backlog to recite
#: when they switch her back on is the opposite of what they asked for.
WAITING_FOR: dict[str, str] = {
    "quiet-hours": "you were asleep",
    "nobody-present": "you were out",
    "conversation-active": "we were talking",
    "cooldown": "I had just said something",
    "daily-budget": "I had run out of thinking for the day",
    "unread": "I could not read it at the time",
}

#: After this, it is history rather than news. The journal still has it.
EXPIRES_AFTER = 12 * 3600.0

#: A waiting room bigger than this is a backlog nobody wants recited. The
#: oldest go first, because the newest is the one still worth hearing.
MOST_HELD = 20

#: How many are handed over at once. One: the mind ticks every couple of
#: minutes, and the cooldown in `policy` spaces the rest out on its own.
#: Releasing the lot the moment somebody walks in the door is how a helpful
#: queue becomes an ambush.
RELEASED_AT_ONCE = 1


@dataclass
class Held:
    """One thing that was worth saying, and why it was not."""

    event: dict[str, Any]
    reason: str
    at: float = field(default_factory=time.time)

    def stale(self, now: float | None = None) -> bool:
        return (time.time() if now is None else now) - self.at > EXPIRES_AFTER

    def explained(self) -> str:
        """"while you were out", or empty when there is nothing to explain."""
        return WAITING_FOR.get(self.reason, "")


class WaitingRoom:
    """Holds what could not be said, and gives it back when it can be.

    Read and written from the mind's thread and from request handlers, so
    everything is behind one lock. Small enough that a list is the right shape.
    """

    def __init__(self, path: Any = None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._held: list[Held] = []
        self._load()

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        if self.path is None:
            return
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(rows, list):
            return
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("event"), dict):
                self._held.append(
                    Held(row["event"], str(row.get("reason", "")), float(row.get("at", 0.0)))
                )
        if self._held:
            log.info("%d thing(s) were still waiting to be said", len(self._held))

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(
                    [{"event": h.event, "reason": h.reason, "at": h.at} for h in self._held],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception as exc:  # pragma: no cover - disk
            log.warning("could not save what is waiting to be said: %s", str(exc)[:160])

    # -- the two things it does ----------------------------------------------

    def hold(self, event: dict[str, Any], reason: str) -> bool:
        """Keep this until `reason` no longer applies. False when it is not held.

        Silently declines reasons that will not pass, and events already
        waiting -- a source that re-reports the same thing every poll must not
        fill the room with copies of it.
        """
        if reason not in WAITING_FOR:
            return False
        identity = _identity(event)
        with self._lock:
            if any(_identity(h.event) == identity for h in self._held):
                return False
            self._held.append(Held(event, reason))
            self._held = [h for h in self._held if not h.stale()][-MOST_HELD:]
            self._save()
        log.info(
            "holding %r until %s passes", str(event.get("summary", ""))[:80], reason,
            extra={"marvi_reason": reason, "marvi_waiting": len(self._held)},
        )
        return True

    def release(self, may_speak: Any) -> list[Held]:
        """Whatever can be said now, oldest first, a few at a time.

        `may_speak(event) -> bool` is asked for each one -- the policy, again,
        against the world as it is now. Nothing is re-decided here; this only
        offers things back to the thing that decides.
        """
        freed: list[Held] = []
        with self._lock:
            keeping: list[Held] = []
            for held in self._held:
                if held.stale():
                    log.info(
                        "dropping %r; it waited too long to be worth saying",
                        str(held.event.get("summary", ""))[:80],
                    )
                    continue
                if len(freed) < RELEASED_AT_ONCE and may_speak(held.event):
                    freed.append(held)
                    continue
                keeping.append(held)
            if freed or len(keeping) != len(self._held):
                self._held = keeping
                self._save()
        for held in freed:
            log.info(
                "saying %r now that %s has passed",
                str(held.event.get("summary", ""))[:80], held.reason,
                extra={"marvi_reason": held.reason},
            )
        return freed

    # -- for the runtime page ------------------------------------------------

    def waiting(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "summary": str(h.event.get("summary", ""))[:200],
                    "reason": h.reason,
                    "because": h.explained(),
                    "waited_seconds": round(time.time() - h.at),
                }
                for h in self._held
            ]

    def forget(self) -> None:
        with self._lock:
            self._held.clear()
            self._save()


def _identity(event: dict[str, Any]) -> str:
    """What makes two events the same thing, for de-duplication."""
    payload = event.get("payload")
    identifier = payload.get("id") if isinstance(payload, dict) else None
    return str(identifier or f"{event.get('source')}:{event.get('kind')}:{event.get('summary')}")
