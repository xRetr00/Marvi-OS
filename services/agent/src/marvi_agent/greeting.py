"""The first thing Marvi says, before anyone has said anything to her.

A call used to open on silence. The room connects, the orb goes green, and
then both sides wait for the other to start -- which is a strange way to be
greeted by something that has been sitting there all day waiting for you.

## What makes this annoying rather than warm

Greeting is easy; greeting *well* is knowing when not to. Three rules, and all
three come from what a person would find irritating:

* **A rejoin is not an arrival.** Hang up, realise you forgot something, come
  back twenty seconds later, and being welcomed again is the assistant not
  noticing it just spoke to you. Inside `SAME_CONVERSATION` she picks up
  instead: "still here", not "good evening".

* **The wake word already is the greeting.** Saying "Marvi" means the next
  thing out of your mouth is the request; opening with a paragraph talks over
  it. There she answers the way a person called by name does -- short, and
  then quiet.

* **Never twice in one stretch.** The greeting belongs to the call, not to
  every reconnection inside it.

## Why it is written and not generated

Same reason as `voicing` in the Gateway: a model would phrase it beautifully
and differently every time, at the cost of a call before every conversation,
on the one path where latency is the whole product. These are ordinary
sentences, and there are enough of them that the same hour twice does not
sound like a recording.
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

from .parakeet_stt import APP_DATA

#: Where the end of the last call is remembered. A job process is created per
#: call and dies with it, so "was I just talking to you" cannot live in memory.
LAST_CALL = APP_DATA / "state" / "voice-last-call"

#: Rejoin inside this and it is the same conversation continuing, not a new
#: one starting. Long enough to cover a dropped connection and a change of
#: mind; short enough that coming back after lunch is still an arrival.
SAME_CONVERSATION = 120.0


def _part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "night"


def _pick(options: tuple[str, ...], seed: int) -> str:
    return options[seed % len(options)]


def opening(
    name: str = "",
    *,
    hour: int = 12,
    since_last_call: float | None = None,
    by_wake_word: bool = False,
    seed: int = 0,
) -> str:
    """What to say on connecting, or empty to stay quiet and listen.

    `since_last_call` is seconds since the previous call ended, or None if
    there has not been one. `by_wake_word` says she was called by name, which
    changes the answer completely: the person is already mid-sentence.
    """
    address = f", {name}" if name else ""

    if by_wake_word:
        # Called by name. Answer the way a person does -- and then get out of
        # the way, because the request is already coming.
        return _pick(("Yes?", f"I am listening{address}.", "Go ahead."), seed)

    if since_last_call is not None and since_last_call < SAME_CONVERSATION:
        # She was just talking to them. Picking the thread back up, not
        # opening a new one.
        return _pick(
            (f"Still here{address}.", "Back with you.", "Go on."),
            seed,
        )

    part = _part_of_day(hour)
    if part == "night":
        # Nobody wants "good night" as a hello at one in the morning, and
        # matching the hour is most of what makes this feel attentive.
        return _pick(
            (
                f"Still up{address}? I am here.",
                f"Late one{address}. What do you need?",
                f"I am here{address}.",
            ),
            seed,
        )
    return _pick(
        (
            f"Good {part}{address}. What can I do?",
            f"Good {part}{address}.",
            # Name without the leading comma: "Hey, Shereef, how can I"
            # has one pause too many for something meant to sound easy.
            f"Hey {name}, how can I help?" if name else "Hey, how can I help?",
        ),
        seed,
    )


def since_last_call(now: float | None = None) -> float | None:
    """Seconds since the last call ended, or None if none is remembered."""
    try:
        ended = LAST_CALL.stat().st_mtime
    except Exception:
        return None
    return max(0.0, (now if now is not None else time.time()) - ended)


def remember_this_call_ended() -> None:
    """Stamp the end of a call, for the next one to read.

    Every failure is swallowed, not just `OSError`: this is a note to the next
    call about how to say hello, and nothing about it is worth ending a
    conversation over. A path that cannot even be constructed raises
    `ValueError` rather than `OSError`, which is how this was found.
    """
    with contextlib.suppress(Exception):
        LAST_CALL.parent.mkdir(parents=True, exist_ok=True)
        LAST_CALL.write_text(str(int(time.time())), encoding="utf-8")


def name_from(user_md_path: Path) -> str:
    """The person's name, read the same way the Gateway reads it.

    Duplicated rather than imported: this runs in the agent's environment,
    which does not have the Gateway on its path, and one regular expression is
    a cheaper dependency than a shared package.
    """
    import re

    try:
        text = user_md_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    heading = re.search(r"^##\s*name\s*$", text, re.I | re.M)
    if not heading:
        return ""
    section = text[heading.end() :].split("\n#", 1)[0]
    if found := re.search(r"^\s*[-*]\s*(.+?)\s*$", section, re.M):
        return re.split(r"[.,(]", found.group(1))[0].strip()
    return ""
