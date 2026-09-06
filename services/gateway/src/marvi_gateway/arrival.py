"""Who just walked in, and how sure Marvi is allowed to be about it.

`presence` answers "is anybody there". This answers the harder one -- "is it
*him*" -- and it is harder because the sensors that detect a person and the
sensors that identify one are not the same sensors, and they fail in different
ways.

## The chain, in the order it actually happens

**OwnTracks says entering home.** The earliest signal by minutes: it fires
while the car is still moving. Nothing is in the room yet and nothing should
be claimed, but it is the moment to put the light on and wait -- being ready
is the whole value of knowing early.

**mmWave says a person is in the room.** Strong, and says nothing about who.

**ESPresense sees the phone.** Now it is probably the owner. Silence here is
not absence: an iPhone in deep sleep stops advertising, so a missing phone is
weak evidence of a missing person.

**The camera recognises a face.** Certainty, and it does not need the other
two: a face is a face whether or not the mmWave is online.

## The edge cases, which are the point

A rule that says "all signals agree, therefore the owner" is not judgement, it
is an `and`. What makes it judgement is what happens when they do not:

* **Camera offline, phone present.** Welcome, but say it is not certain and
  ask them to check their phone -- the phone *is* the identity here.
* **Camera offline, no phone, but the phone's battery was dying.** The silence
  is explained. Welcome with an honest hedge rather than treating them as a
  stranger, because the likeliest reason a dead phone stopped advertising is
  that it is dead.
* **Battery fine, OwnTracks says away, phone not in the room, and mmWave says
  somebody is.** That is not the owner. Put the light on, take photographs,
  greet the visitor, and tell the owner when they come back -- with the
  pictures.

The third one is why this file exists. The same four booleans, read as a set,
produce "somebody is here"; read as a *situation* they produce "somebody who
is not you is in your room while you are out", and only one of those is worth
waking up for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .logs import get_logger

log = get_logger("mind")

#: Below this, a phone going quiet is more likely flat than gone.
#:
#: Not a guess: the owner's own OwnTracks log has reports at 10% and 20%, and
#: `bs=1` (unplugged) on both. A phone at 15% that stops advertising has an
#: obvious explanation and should not turn its owner into an intruder.
BATTERY_LOW = 25

#: Battery status from OwnTracks: 0 unknown, 1 unplugged, 2 charging, 3 full.
UNPLUGGED = 1


@dataclass(frozen=True)
class Who:
    """What Marvi believes about the person in the room, and how firmly."""

    #: `owner`, `stranger`, `probably_owner`, `unsure`, or `nobody`.
    verdict: str
    #: 0..1. Used to decide whether to greet warmly, hedge, or photograph.
    confidence: float
    #: One sentence, in the words she would use.
    because: str
    #: What she should do about it beyond speaking.
    watch: bool = False
    #: What to say, when the situation calls for something specific.
    say: str = ""
    signals: dict[str, Any] = field(default_factory=dict)

    @property
    def is_owner(self) -> bool:
        return self.verdict in ("owner", "probably_owner")


def _fresh(signal: Any) -> bool | None:
    """A signal's opinion, or None when it is stale, absent or has none."""
    if signal is None:
        return None
    return signal.says if signal.counts else None


def expecting(location: dict[str, Any]) -> bool:
    """Whether the owner is on their way in.

    True from an `enter home` transition until something in the room fires.
    This is the minutes of warning OwnTracks gives while somebody is still
    parking, and the only thing worth doing with it is getting ready -- the
    light on, the models warm -- because claiming they have arrived on the
    strength of a phone crossing a line is how you greet an empty room.
    """
    return bool(location.get("home")) and str(location.get("zone") or "") == "home"


def where(location: dict[str, Any]) -> str:
    """Which region the phone is in, said the way a person would.

    `regions` first: it is level-triggered and survives a missed transition,
    which `zone` alone does not. Empty means outside every region, which is a
    real answer and reads as "out" rather than as "unknown".
    """
    regions = location.get("regions")
    if isinstance(regions, list):
        return str(regions[0]).strip().lower() if regions else "out"
    zone = str(location.get("zone") or "").strip().lower()
    return zone or "unknown"


def phone_can_be_believed(location: dict[str, Any]) -> tuple[bool, str]:
    """Whether a *silent* phone means its owner is not here.

    The whole question is what an absence proves, and the answer depends on
    the battery: a phone that stopped talking at 8% stopped because it died.
    """
    percent = location.get("battery_percent")
    state = location.get("battery_state")
    if percent is None:
        return True, ""
    try:
        percent = int(percent)
    except (TypeError, ValueError):
        return True, ""
    if percent <= BATTERY_LOW and (state is None or int(state) == UNPLUGGED):
        return False, f"their phone was down to {percent}%"
    return True, ""


def judge(state: dict[str, Any], found: list[Any]) -> Who:
    """Who is in the room, from the sensors and the situation around them.

    `found` is `presence.signals(state)` -- already normalised and already
    aged, so a stale reading has no opinion here rather than an old one.
    """
    by_source = {signal.source: signal for signal in found}
    person = _fresh(by_source.get("mmwave"))
    seen = _fresh(by_source.get("camera"))
    phone_here = _fresh(by_source.get("bluetooth"))
    location = state.get("location") if isinstance(state.get("location"), dict) else {}
    vision = state.get("vision") if isinstance(state.get("vision"), dict) else {}
    owner_face = bool(vision.get("owner_visible"))
    unknown_faces = int(vision.get("unknown_count") or 0)

    signals = {
        "mmwave": person,
        "camera": seen,
        "phone": phone_here,
        "region": where(location),
        "battery": location.get("battery_percent"),
    }

    # Nothing at all. Not "nobody" -- nobody is a claim, and no working sensor
    # is not in a position to make one.
    if person is None and seen is None and phone_here is None:
        return Who("unsure", 0.0, "nothing can see the room right now", signals=signals)

    # Nobody, whatever the phone says.
    #
    # A phone is not a person -- it sits on the desk while its owner is out --
    # so it cannot carry this on its own. Checked before the phone branch
    # below, because with the order the other way round a phone left charging
    # in an empty room read as "probably the owner, welcome back", which is
    # exactly what running this against the real room produced.
    somebody = person is True or (seen is True)
    if not somebody and (person is False or seen is False):
        return Who("nobody", 0.8, "the room reads empty", signals=signals)

    # The camera settles it, and does not need the others. A face is a face
    # whether or not the mmWave is online.
    if seen is True and owner_face:
        return Who("owner", 0.95, "the camera recognised them", signals=signals)

    if seen is True and unknown_faces and not owner_face:
        return Who(
            "stranger",
            0.9,
            f"the camera sees {unknown_faces} face{'s' if unknown_faces > 1 else ''} it does not know",
            watch=True,
            say="Someone I do not recognise is in the room.",
            signals=signals,
        )

    # No camera, but something knows a person is here. The phone is the
    # identity now -- and only now, because it is identity, not detection.
    if somebody and phone_here is True:
        return Who(
            "probably_owner",
            0.7,
            "their phone is in the room, but nothing has seen a face",
            say="Welcome back. I think it is you -- I cannot see well enough to be sure.",
            signals=signals,
        )

    # Somebody is here and their phone is not. Whether that is alarming turns
    # entirely on whether the phone had a reason to go quiet.
    if person is True and phone_here is not True:
        believable, excuse = phone_can_be_believed(location)
        if not believable:
            return Who(
                "probably_owner",
                0.5,
                f"somebody is here and {excuse}, so the phone proves nothing",
                say=(
                    "Welcome back — I think it is you. Your phone has gone quiet, "
                    "so I cannot be certain."
                ),
                signals=signals,
            )
        region = where(location)
        if region not in ("home", "unknown"):
            # The strong case. Battery fine, phone somewhere else entirely,
            # and something is moving in the room.
            return Who(
                "stranger",
                0.85,
                f"somebody is in the room and their phone is {region}",
                watch=True,
                say="There is someone in the room, and it is not you.",
                signals=signals,
            )
        return Who(
            "unsure",
            0.4,
            "somebody is here and nothing can say who",
            say="Someone is here. I cannot tell who — could you check your phone?",
            signals=signals,
        )

    return Who("unsure", 0.3, "the sensors do not add up to an answer", signals=signals)
