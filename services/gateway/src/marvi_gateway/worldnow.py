"""What is true about the world right now, as one line for the prompt.

The Mind reads the room, the desktop and the journal to decide whether to
interrupt. Marvi — the one actually talking to you — read none of it. Asked
"what am I doing", she had no way to know; asked "is anyone home", she had to
call a tool and hope the room answered.

Worse, the pieces reached her by separate paths when they reached her at all:
room state through a tool, activity through a different tool, presence not at
all. So the same question got a different answer depending on which tool the
model happened to think of.

One block, assembled where the Mind already assembles it, on every turn of both
surfaces. If the Mind knows it, Marvi knows it.

## Why it is short, and why it never says "probably"

Paid on every turn of every conversation. Names what is known and omits what is
not — a line saying "presence unknown" costs the same as one saying nothing and
invites the model to speculate about it out loud.

## Why the room is not asked here

`snapshot()` is served from the sidecar's own cache. This composes what the
Gateway already holds; it never adds a round trip to a spoken turn.
"""

from __future__ import annotations

from typing import Any

#: Beyond this the block stops being context and starts being a report.
MAX_CHARS = 320


def _room_line(snapshot: dict[str, Any] | None) -> str:
    if not snapshot:
        return ""
    parts: list[str] = []
    light = snapshot.get("light") or {}
    modes = snapshot.get("modes") or {}
    presence = snapshot.get("presence") or {}
    if light:
        parts.append(
            f"the light is on at {light.get('brightness', '?')}%"
            if light.get("on")
            else "the light is off"
        )
    if mode := modes.get("active_mode"):
        parts.append(f"the room is in {mode} mode")
    if presence:
        parts.append("someone is in the room" if presence.get("detected") else "the room is empty")
    return ", ".join(parts)


def describe(
    room: dict[str, Any] | None = None,
    activity: dict[str, Any] | None = None,
    *,
    recent_apps: list[str] | None = None,
) -> str:
    """The world block, or "" when nothing is known.

    Every part is optional and an absent one is simply not mentioned. A machine
    with no room plugin and no ActivityWatch produces nothing at all, which is
    correct: there is no world context to give.
    """
    lines: list[str] = []
    if room_line := _room_line(room):
        lines.append(room_line)
    if activity:
        summary = str(activity.get("summary") or "").strip()
        # "no activity data" is the adapter's way of saying it cannot see, and
        # repeating that to the model invites her to announce it.
        if summary and summary != "no activity data":
            lines.append(f"they are {summary}")
    if recent_apps:
        lines.append("today they have used " + ", ".join(recent_apps[:5]))
    if not lines:
        return ""
    body = "; ".join(lines)
    if len(body) > MAX_CHARS:
        body = body[: MAX_CHARS - 1].rstrip(" ,;") + "…"
    return (
        "# What is happening right now\n\n"
        f"{body[0].upper()}{body[1:]}.\n"
        "This is what your own senses report, not something you were told. "
        "Use it when it bears on the question and never recite it."
    )
