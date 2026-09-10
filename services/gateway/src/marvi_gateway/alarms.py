"""Failures worth saying out loud, said once.

The announcer is the part of Marvi that keeps working when the rest does not.
It has its own small model, its own audio path, and no dependency on the voice
session, the browser, the room, or a provider being reachable. When something
big breaks, it is usually the only thing left that can tell you.

Until now it was only used for things Marvi *chose* to say. Meanwhile the
failures nobody could miss were going to a log file:

    another Marvi is holding port 8765
    VoXtream2 failed to load: No espeak backend found
    the camera cannot be read: no cv2 module

Each of those makes a whole capability stop, each was known the moment it
happened, and each was discovered hours later by a person reading logs and
wondering why Marvi was behaving oddly.

## Once, not continuously

A broken thing stays broken, and `current_status` runs on every poll. Saying
"the browser engine is missing" every two seconds would be worse than silence
-- it would be the thing you turn off, and then it is silence anyway. So each
distinct failure is spoken once, and again only if it clears and returns.

## Only what a person would want interrupting for

A component in `error` has stopped working entirely. A `degraded` or
`starting` one has not, and says so on screen where it belongs. Speaking the
lesser states would make the alarm ordinary, and an ordinary alarm is ignored.
"""

from __future__ import annotations

import threading
from typing import Any

from .logs import get_logger

log = get_logger("gateway")

#: Components whose failure is worth a spoken line, and how to say it.
#:
#: Written as a sentence a person hears once, out of context, possibly from
#: another room -- so it names the thing that stopped and what it costs,
#: never a state name or an exception. "Voice is in an error state" tells
#: somebody nothing they can act on.
WORTH_SAYING = {
    "gateway": "Something is wrong with my gateway, so most of what I do is unavailable.",
    "voice": "My voice could not start, so I cannot hold a conversation until it is fixed.",
    "room": "I have lost the room, so I cannot see or change anything in it.",
    "vision": "My camera has stopped working, so I cannot see the room.",
    "browser": "My browser could not start, so I cannot open pages.",
    "computer": "Computer control could not start, so I cannot use the desktop.",
}

#: The state that counts as broken. See the module docstring.
BROKEN = "error"


class Alarms:
    """What has already been said, so it is not said again."""

    def __init__(self, announcer: Any = None) -> None:
        self.announcer = announcer
        self._said: set[str] = set()
        self._lock = threading.Lock()

    def _wording(self, name: str, detail: str) -> str:
        line = WORTH_SAYING.get(name)
        if not line:
            return ""
        # The detail is developer text -- an exception, a path, a status code.
        # It goes to the log, never to the speaker.
        log.warning("alarm: %s is broken: %s", name, detail or "no detail")
        return line

    def check(self, components: dict[str, Any]) -> list[str]:
        """Speak anything newly broken. Returns what was said, for tests."""
        spoken: list[str] = []
        for name, status in (components or {}).items():
            state = getattr(status, "state", None) or (
                status.get("state") if isinstance(status, dict) else None
            )
            detail = getattr(status, "detail", "") or (
                status.get("detail", "") if isinstance(status, dict) else ""
            )
            with self._lock:
                if state != BROKEN:
                    # Recovered, so the next failure is news again.
                    self._said.discard(name)
                    continue
                if name in self._said:
                    continue
                line = self._wording(name, str(detail))
                if not line:
                    continue
                self._said.add(name)
            self._say(line)
            spoken.append(line)
        return spoken

    def _say(self, line: str) -> None:
        """Never raises, and never blocks the caller.

        This runs from the status path, which the shell polls. An announcer
        that is slow to warm, or absent entirely, must not make reading the
        status slow or make it fail -- the whole point is that this is the
        channel that still works when other things do not.
        """
        from .announce import announce_enabled

        if self.announcer is None or not announce_enabled():
            return
        threading.Thread(
            target=self._speak_now, args=(line,), name="marvi-alarm", daemon=True
        ).start()

    def _speak_now(self, line: str) -> None:
        try:
            self.announcer.speak(line, purpose="proactive", source="alarm")
        except Exception as exc:  # pragma: no cover - depends on the audio stack
            log.warning("could not announce a failure: %s", exc)

    def forget(self) -> None:
        """For tests, and after a deliberate restart."""
        with self._lock:
            self._said.clear()
