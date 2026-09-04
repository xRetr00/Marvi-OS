"""Saying what went wrong, in her own voice, instead of going quiet.

Marvi's failures were legible only in a log file. From outside, a rate-limited
model, an unreachable Gateway and a recogniser that heard nothing all looked
identical: a pause, and then nothing. The person repeats themselves into
silence and eventually stops asking, which is the failure mode that makes an
assistant feel dead rather than broken.

The pipeline already knows. `providers.log` has the exact reason, to the
millisecond:

    provider openrouter cooling down 300s: rate limited or window exhausted
    auxiliary task failed; using deterministic result | 'No provider is
    available; all are unconfigured or cooling down.'

Thirty-eight of those in one afternoon, and Marvi said nothing about any of
them. Somebody sitting there was owed one sentence.

## Why the text is written here and never taken from the error

Nothing in this module echoes an exception. Every line is a fixed string
chosen by matching against the fault; the fault itself is only ever read, not
repeated. That is deliberate and it is not stylistic: provider errors carry
request URLs and auth headers, and an assistant that reads its exceptions out
loud is an assistant that reads an API key out loud, to whoever is in the
room and into the transcript that goes to a model.

## Why it stays quiet more often than not

An unrecognised fault gets no line at all. A narrator that says "something
went wrong" on every unknown error is worse than silence: it is noise that
teaches the person to ignore it, and it says nothing they can act on. Only
faults with a name and a consequence somebody can do something about are
worth interrupting for.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Trouble:
    """Something worth saying out loud, and how often it may be said."""

    #: What identifies this fault in the text of an error. Matched
    #: case-insensitively against the rendered exception.
    pattern: re.Pattern[str]
    #: What Marvi says. Written here; never assembled from the error.
    line: str
    #: How long before this may be said again. A model that is cooling down
    #: for five minutes will fail every turn in that window, and hearing the
    #: same sentence six times is worse than hearing it once.
    quiet_for: float


#: The faults worth a sentence, most specific first.
#:
#: Each line says the thing and its consequence, because "OpenRouter is rate
#: limiting me" alone leaves the person waiting to find out whether that means
#: five seconds or the rest of the evening.
TROUBLES: tuple[Trouble, ...] = (
    Trouble(
        re.compile(r"rate limit|429|window exhausted|cooling down", re.I),
        "The model provider is rate limiting me, so I am on the slower path for "
        "a few minutes. I will still answer, just less quickly.",
        300.0,
    ),
    Trouble(
        re.compile(r"no provider is available|unconfigured", re.I),
        "I have no language model configured right now, so I can hear you but I "
        "cannot think. Connecting one in the control center fixes it.",
        300.0,
    ),
    Trouble(
        re.compile(r"gateway is unreachable|connection refused|failed to connect", re.I),
        "I have lost my connection to the Gateway, so my tools and memory are "
        "not reachable at the moment.",
        120.0,
    ),
    Trouble(
        re.compile(r"a local token is required|403", re.I),
        "The Gateway is refusing me its credentials, which usually means it was "
        "left running from an earlier launch. Restarting Marvi fixes it.",
        300.0,
    ),
    Trouble(
        re.compile(r"insufficient credit|payment required|402|quota", re.I),
        "The model provider says the account is out of credit, so I cannot "
        "answer properly until that is topped up.",
        600.0,
    ),
    Trouble(
        re.compile(r"tts|speech synthesis|voice sidecar", re.I),
        "My voice engine had to restart, so I may be a moment behind for the "
        "next answer.",
        60.0,
    ),
    Trouble(
        re.compile(r"timed out|timeout", re.I),
        "That took longer than it should have and timed out. Ask me again and I "
        "will try a different way.",
        60.0,
    ),
)


class Narrator:
    """Decides whether a fault is worth saying, and does not repeat itself."""

    def __init__(self) -> None:
        self._said: dict[str, float] = {}

    def speak_about(self, error: object, *, now: float | None = None) -> str:
        """One sentence about this fault, or empty to stay quiet.

        `error` is read and never repeated: see the note in the module
        docstring about what provider exceptions carry.
        """
        text = self._render(error)
        if not text:
            return ""
        moment = time.monotonic() if now is None else now
        for trouble in TROUBLES:
            if not trouble.pattern.search(text):
                continue
            last = self._said.get(trouble.line)
            if last is not None and moment - last < trouble.quiet_for:
                return ""
            self._said[trouble.line] = moment
            return trouble.line
        return ""

    @staticmethod
    def _render(error: object) -> str:
        """The fault as text, defensively.

        A `__str__` that raises must not take down the turn it is reporting on.
        """
        try:
            return str(error)
        except Exception:
            return ""
