"""What Marvi says out loud, in the words a person would use.

The announcer read `event["summary"]` verbatim, and a summary is written for a
journal: `room:light_changed — light 80% (warm)`. Spoken aloud that is a status
line, and a status line read by a voice is the thing that makes an assistant
feel like a monitoring dashboard somebody strapped a speaker to.

The difference is not politeness, it is *stance*. A dashboard reports on the
world. An assistant tells you what it did, or noticed, for you:

    room status changed, the lights are on
    -> Hey Shereef, I turned the lights on for you.

    presence detected while location is not home
    -> Shereef, someone just walked into the room and you are not home.

    gateway component degraded
    -> Hey Shereef, I noticed something wrong with my Gateway connection.

## Why these are written and not generated

A model could phrase these and would phrase them differently every time, which
sounds alive right up until it costs a call per light switch. The Mind already
refuses to spend a model on repetitive events for exactly that reason -- see
`salience` -- and a line that only exists to be warm is the last thing worth
paying for. So the words are here, several per situation, and which one comes
out depends on the event so that the same thing twice does not sound like a
recording.

Anything this does not recognise returns empty, and the caller keeps whatever
it had. Being unable to phrase something warmly is not a reason to say nothing,
and it is not a reason to guess.

## The name

From `USER.md`, which is where the person is described. Used where a person
would use it -- greeting, or catching your attention -- and left out of the
rest, because being addressed by name in every single sentence is its own kind
of robot.
"""

from __future__ import annotations

import re
from typing import Any

#: Where the person's name lives. `USER.md` is a document, not a schema, so
#: this reads the shape it actually has rather than requiring one.
_NAME_HEADING = re.compile(r"^##\s*name\s*$", re.I | re.M)
_FIRST_BULLET = re.compile(r"^\s*[-*]\s*(.+?)\s*$", re.M)


def name_of(user_md: str) -> str:
    """The name to call them, or empty if the file does not say.

    Empty is a normal answer and the lines below all read correctly without a
    name. Inventing one, or falling back to "user", is worse than not using it.
    """
    heading = _NAME_HEADING.search(user_md or "")
    if not heading:
        return ""
    after = user_md[heading.end() :]
    # Stop at the next section: the first bullet under *this* heading.
    section = after.split("\n#", 1)[0]
    if found := _FIRST_BULLET.search(section):
        # "Shereef." and "Shereef (he/him)" are both things a person writes.
        return re.split(r"[.,(]", found.group(1))[0].strip()
    return ""


def _choose(options: tuple[str, ...], event: dict[str, Any]) -> str:
    """One of several phrasings, stable for a given event.

    Rotating on the event's own content rather than at random: the same event
    phrases the same way, which keeps this testable, while two different
    lights, or the same light an hour apart, do not read like a loop.
    """
    seed = f"{event.get('kind', '')}{event.get('summary', '')}{event.get('at', '')}"
    return options[sum(map(ord, seed)) % len(options)]


def _greeting(name: str) -> str:
    return f"Hey {name}, " if name else "Hey, "


def _address(name: str) -> str:
    return f"{name}, " if name else ""


def _on(payload: dict[str, Any], *names: str) -> Any:
    for key in names:
        if key in payload:
            return payload[key]
    return None


def _lights(event: dict[str, Any], name: str, payload: dict[str, Any]) -> str:
    on = _on(payload, "on", "is_on")
    if on is False:
        return _choose(
            (
                f"{_greeting(name)}I turned the lights off.",
                f"{_greeting(name)}lights are off now.",
            ),
            event,
        )
    brightness = _on(payload, "brightness")
    warmth = ""
    if isinstance(brightness, (int, float)) and brightness:
        warmth = f" at {int(brightness)} percent"
    return _choose(
        (
            f"{_greeting(name)}I turned the lights on for you{warmth}.",
            f"{_greeting(name)}lights are on{warmth} — let me know if that is too much.",
        ),
        event,
    )


def _visitor(event: dict[str, Any], name: str, away: bool | None) -> str:
    if away:
        # The one case where this stops being pleasant and starts being the
        # reason the feature exists.
        return _choose(
            (
                f"{_address(name)}someone just walked into the room, and you are not home.",
                f"{_address(name)}there is someone in the room while you are out.",
            ),
            event,
        )
    return _choose(
        (
            f"{_greeting(name)}someone just came in.",
            f"{_greeting(name)}you have company — someone is in the room.",
        ),
        event,
    )


def _home(event: dict[str, Any], name: str) -> str:
    return _choose(
        (
            f"Welcome back{', ' + name if name else ''}. How was your day?",
            f"Welcome home{', ' + name if name else ''} — good to have you back.",
            f"{_greeting(name)}I noticed you are home. How did it go?",
        ),
        event,
    )


def _work(event: dict[str, Any], name: str, zone: str) -> str:
    where = zone or "work"
    return _choose(
        (
            f"{_greeting(name)}I see you made it to the {where}.",
            f"{_greeting(name)}you are at the {where} — I will keep things quiet here.",
        ),
        event,
    )


def _left(event: dict[str, Any], name: str) -> str:
    return _choose(
        (
            f"{_greeting(name)}I noticed you headed out. I will watch the place.",
            f"See you{', ' + name if name else ''} — I will keep an eye on things.",
        ),
        event,
    )


def _trouble(event: dict[str, Any], name: str, what: str) -> str:
    return _choose(
        (
            f"{_greeting(name)}I noticed something wrong with my {what}.",
            f"{_greeting(name)}I am having trouble with my {what} — I may be slower than usual.",
            f"{_address(name)}my {what} is not behaving. I am still here, just limited.",
        ),
        event,
    )


#: What a component is called out loud. "gateway" is a word Marvi uses about
#: herself; the rest are the names a person would recognise.
PARTS = {
    "gateway": "Gateway connection",
    "livekit": "voice connection",
    "agent": "voice worker",
    "smart_room": "room connection",
    "room": "room connection",
    "memory": "memory",
}


def spoken(
    event: dict[str, Any],
    name: str = "",
    *,
    away: bool | None = None,
) -> str:
    """A warm line for this event, or empty to leave it to the caller.

    `away` is whether the person is somewhere other than home, as far as
    anything knows. It only changes the visitor line, and only because "someone
    is in the room" means something entirely different when you are out.
    """
    kind = f"{event.get('source', '')}:{event.get('kind', '')}"
    payload = event.get("payload")
    payload = payload if isinstance(payload, dict) else {}

    if kind in ("room:light_changed", "room:lights_changed"):
        return _lights(event, name, payload)
    if kind in (
        "room:visitor_report",
        "room:vision_visitor_seen",
        "room:room_entry",
        "room:presence_detected",
        "vision:visitor_report",
    ):
        return _visitor(event, name, away)
    if kind in ("room:room_welcome", "room:owner_home", "presence:home", "vision:owner_seen"):
        return _home(event, name)
    if kind in ("presence:work", "presence:arrived_work"):
        return _work(event, name, str(_on(payload, "zone", "place") or ""))
    if kind in ("presence:left", "presence:away", "room:presence_cleared"):
        return _left(event, name)
    if kind in ("system:degraded", "system:component_failed", "room:device_offline"):
        component = str(_on(payload, "component", "name", "device") or "")
        return _trouble(event, name, PARTS.get(component, component or "connection"))
    return ""
