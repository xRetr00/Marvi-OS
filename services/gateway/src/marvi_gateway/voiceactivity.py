"""What Marvi is doing right now, for the Voice page to show.

The Voice page could say which models were loaded and nothing about the work.
A spoken turn that pauses for four seconds looked identical whether she was
searching the web, waiting on a room bridge, or had simply stopped -- and the
transcript, which is the only other surface, shows the answer after it exists
rather than the reaching for it.

Chat has had this the whole time: a context meter in the status bar and a
collapsed "Used N tools" stack under each answer. Voice had neither, on the
surface where you cannot scroll back.

## Why it lives here and not in the transcript

A tool call is not speech. Putting it through `/voice/transcript` would put
"searched the web" in the same list as the things Marvi said, which is the
third-person problem in another costume -- the page would be narrating her.

## Why it is a ring and not a log

`observations.jsonl` already keeps the durable record and is read by the evals.
This is the live surface: what is happening now and what happened this session,
bounded, in memory, gone when the process ends. A page that has to page through
history is a page nobody watches.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

#: One session's worth of calls. Long enough to scroll, short enough that the
#: whole thing renders without virtualisation.
KEEP = 60

#: A call still counts as running until this long after it started. Nothing
#: reports completion for a tool the Agent abandoned, and a spinner that never
#: stops is worse than one that gives up.
RUNNING_FOR = 30.0


class Activity:
    """The tool calls and token usage of the session in front of the user."""

    def __init__(self, keep: int = KEEP) -> None:
        self._calls: deque[dict[str, Any]] = deque(maxlen=keep)
        self._lock = threading.Lock()
        self._used = 0
        self._window = 0
        self._turns = 0

    def began(self, tool: str, arguments: dict[str, Any] | None = None) -> str:
        """A call started. Returns the id its outcome should be reported with."""
        call_id = f"{tool}-{time.time():.6f}"
        with self._lock:
            self._calls.append(
                {
                    "id": call_id,
                    "tool": tool,
                    "arguments": arguments or {},
                    "outcome": "running",
                    "at": time.time(),
                    "ms": 0,
                }
            )
        return call_id

    def ended(self, call_id: str, outcome: str, detail: str = "") -> None:
        with self._lock:
            for call in reversed(self._calls):
                if call["id"] == call_id:
                    call["outcome"] = outcome
                    call["detail"] = detail[:200]
                    call["ms"] = int((time.time() - call["at"]) * 1000)
                    return

    def counted(self, used: int, window: int, turns: int = 0) -> None:
        """How full the model's context is, as the Agent last measured it."""
        with self._lock:
            self._used = max(0, used)
            self._window = max(0, window)
            if turns:
                self._turns = turns

    def cleared(self) -> None:
        """A new session. The page is about this call, not the last one."""
        with self._lock:
            self._calls.clear()
            self._used = self._window = self._turns = 0

    def state(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            calls = [dict(call) for call in self._calls]
            used, window, turns = self._used, self._window, self._turns
        for call in calls:
            # Abandoned rather than running. See RUNNING_FOR: nothing reports
            # completion for a call the Agent gave up on, and a spinner that
            # never stops reads as the page being broken.
            if call["outcome"] == "running" and now - call["at"] > RUNNING_FOR:
                call["outcome"] = "abandoned"
        return {
            "calls": list(reversed(calls)),
            "running": sum(1 for call in calls if call["outcome"] == "running"),
            "context": {"used": used, "window": window, "turns": turns},
        }


#: One per Gateway, because there is one voice session at a time.
live = Activity()
