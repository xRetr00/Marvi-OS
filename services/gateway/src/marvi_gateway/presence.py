"""Who is in the room, when the sensors disagree.

Four things report on the room and none of them is authoritative:

* **mmWave (the ESP32)** sees motion and breathing. It misses someone perfectly
  still and it fires on a curtain.
* **The camera** sees faces. It sees nothing in the dark, nothing behind it, and
  it cannot tell a photograph from a person.
* **OwnTracks** says the phone is home. A phone is not a person: it is on the
  desk while its owner is out, and in a pocket two rooms away.
* **Bluetooth presence** is the same story with worse resolution, and its
  silence is famously not absence -- an iPhone in deep sleep stops advertising.

The old arrangement resolved these with fixed rules inside the sidecar. That is
right for the cases where they agree, which is most of the time, and wrong for
every case worth having an opinion about: the sensor that sees nobody while
another sees someone, the phone that says home while the room says empty, the
face nobody has met before.

## Rules where they agree, judgement where they do not

A model is asked *only* when the signals conflict or something is unrecognised.
When every source that has an opinion agrees, the answer is arithmetic and
costs nothing -- which matters, because this runs on a poll and a model call
per poll would be both slow and expensive.

That split is the whole design. It is also why the deterministic path is the
one with the tests: it decides almost every case.

## What it does not do

It does not touch a device. This says who is present and how sure it is;
what to do about that stays where it already was. A presence reading that
silently switched a light would be a rule again, just further away.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from . import auxiliary
from .logs import get_logger

log = get_logger("presence")

#: How old a reading may be before it is reported as unknown rather than as
#: what it last said. A sensor that stopped talking an hour ago is not evidence
#: that the room is empty; it is evidence about the sensor.
STALE_AFTER = 180.0

MAX_OUTPUT_TOKENS = 200

SYSTEM_PROMPT = (
    "You decide who is in a room from sensors that disagree. You produce one "
    "JSON object and nothing else.\n"
    'Reply exactly: {"present": true|false, "who": "owner|someone|nobody|unknown", '
    '"confidence": 0.0-1.0, "why": "<one short sentence>"}\n'
    "Weigh the sensors by what each can actually know. A camera that sees a "
    "face is strong evidence someone is there and weak evidence about who is "
    "not. Motion sensors miss people sitting still. A phone at home means the "
    "phone is at home. Silence from any sensor is not evidence of absence.\n"
    "Prefer 'unknown' with low confidence over a confident guess: something "
    "downstream will act on this, and being unsure is a useful answer."
)


@dataclass
class Signal:
    """One sensor's opinion, and how much it is worth."""

    source: str
    #: True, False, or None for "this sensor has no opinion right now".
    says: bool | None
    detail: str = ""
    #: Seconds since the reading. None when the sensor does not timestamp.
    age: float | None = None
    confidence: float = 0.0

    @property
    def stale(self) -> bool:
        return self.age is not None and self.age > STALE_AFTER

    @property
    def counts(self) -> bool:
        """Whether this signal is worth weighing at all."""
        return self.says is not None and not self.stale

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "says": self.says,
            "detail": self.detail,
            "age": None if self.age is None else round(self.age, 1),
            "confidence": round(self.confidence, 2),
            "stale": self.stale,
        }


@dataclass
class Reading:
    """What Marvi concludes, and everything needed to argue with it."""

    present: bool
    who: str
    confidence: float
    why: str
    #: True when a model was asked. False means the sensors agreed and the
    #: answer is arithmetic.
    judged: bool = False
    signals: list[Signal] = field(default_factory=list)
    unknown_faces: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "who": self.who,
            "confidence": round(self.confidence, 2),
            "why": self.why,
            "judged": self.judged,
            "unknown_faces": self.unknown_faces,
            "signals": [signal.as_dict() for signal in self.signals],
        }


def _age(value: Any, now: float) -> float | None:
    """Seconds since a timestamp the sidecar reported, or None."""
    if isinstance(value, int | float) and value > 0:
        # Epoch seconds; anything else is not a timestamp we understand.
        return max(0.0, now - float(value)) if value > 1_000_000_000 else None
    return None


def signals(state: dict[str, Any], now: float | None = None) -> list[Signal]:
    """Every sensor's opinion, normalised.

    Reading each source into the same shape is what makes disagreement
    visible. Before this they were four differently-named blobs in one state
    dictionary and nothing ever compared them.
    """
    now = now or time.time()

    def block(key: str) -> dict[str, Any]:
        value = state.get(key)
        return value if isinstance(value, dict) else {}

    mmwave, vision = block("mmwave"), block("vision")
    location, presence = block("location"), block("presence")

    people = int(vision.get("person_count") or 0)
    # A camera reporting an error, a stale frame, or nothing at all has no
    # opinion, rather than the opinion "nobody". That distinction is the whole
    # point of this module, and an absent block is the easiest way to get it
    # wrong: an empty dict read as "zero people seen" rather than "no camera".
    camera_blind = not vision or bool(vision.get("error")) or bool(vision.get("stale"))

    return [
        Signal(
            source="mmwave",
            says=bool(mmwave.get("occupied")) if mmwave else None,
            detail="motion and breathing; misses someone sitting still",
            age=_age(mmwave.get("last_seen"), now),
            confidence=0.6,
        ),
        Signal(
            source="camera",
            says=None if camera_blind else people > 0,
            detail=(
                str(vision.get("error"))
                if vision.get("error")
                else f"{people} seen"
                + (", owner recognised" if vision.get("owner_visible") else "")
            ),
            age=_age(vision.get("last_inference_at"), now),
            confidence=float(vision.get("owner_confidence") or 0.0) or (0.8 if people else 0.5),
        ),
        Signal(
            source="phone",
            says=bool(location.get("home")) if location.get("source") else None,
            detail=f"OwnTracks says {location.get('zone') or 'unknown'}; a phone is not a person",
            age=_age(location.get("last_geofence_at"), now),
            confidence=0.4,
        ),
        Signal(
            source="bluetooth",
            says=bool(presence.get("detected")) if presence.get("source") not in (None, "none")
            else None,
            detail="silence is not absence; a sleeping phone stops advertising",
            age=_age(presence.get("last_seen"), now),
            confidence=float(presence.get("confidence") or 0.0),
        ),
    ]


def disagree(found: list[Signal]) -> bool:
    """Whether any two sensors that both have an opinion hold different ones."""
    opinions = {signal.says for signal in found if signal.counts}
    return len(opinions) > 1


def read(state: dict[str, Any], client: Any = None, now: float | None = None) -> Reading:
    """Who is in the room. Asks a model only when the sensors conflict.

    Always logs every signal and how the answer was reached, because the whole
    reason this exists is that "presence: false" told nobody which sensor said
    so or whether anything disagreed.
    """
    found = signals(state, now)
    vision = state.get("vision") if isinstance(state.get("vision"), dict) else {}
    unknown = int(vision.get("pending_visitors") or 0)
    speaking = [signal for signal in found if signal.counts]

    conflict = disagree(found)
    reading = (
        _judge(found, unknown, client)
        if (conflict or unknown) and client is not None
        else _arithmetic(found, speaking, conflict, unknown)
    )
    reading.signals = found
    reading.unknown_faces = unknown

    log.info(
        "presence: %s (%s, %.0f%%) %s",
        "someone" if reading.present else "nobody",
        reading.who,
        reading.confidence * 100,
        "judged" if reading.judged else "agreed",
        extra={
            "marvi_present": str(reading.present),
            "marvi_who": reading.who,
            "marvi_confidence": f"{reading.confidence:.2f}",
            "marvi_judged": str(reading.judged),
            "marvi_conflict": str(conflict),
            "marvi_unknown_faces": str(unknown),
            "marvi_why": reading.why,
            # Every input, so a wrong answer can be argued with from the log
            # alone rather than reproduced.
            "marvi_signals": json.dumps([signal.as_dict() for signal in found]),
        },
    )
    return reading


def _arithmetic(
    found: list[Signal], speaking: list[Signal], conflict: bool, unknown: int
) -> Reading:
    """The answer when nothing disagrees, or when there is no model to ask."""
    if not speaking:
        return Reading(
            present=False,
            who="unknown",
            confidence=0.0,
            why="No sensor has a current reading.",
            judged=False,
        )
    present = any(signal.says for signal in speaking)
    best = max((s.confidence for s in speaking if s.says is present), default=0.5)
    if conflict:
        # No model, and they disagree: say so rather than picking a winner.
        return Reading(
            present=present,
            who="unknown",
            confidence=min(best, 0.4),
            why="Sensors disagree and there is no model configured to weigh them.",
            judged=False,
        )
    camera = next((s for s in speaking if s.source == "camera"), None)
    owner = bool(camera and camera.says and "owner recognised" in camera.detail)
    return Reading(
        present=present,
        who=("owner" if owner else "someone") if present else "nobody",
        confidence=best,
        why=", ".join(f"{s.source} says {'yes' if s.says else 'no'}" for s in speaking) + ".",
        judged=False,
    )


def _judge(found: list[Signal], unknown: int, client: Any) -> Reading:
    """Ask a model to weigh sensors that disagree. Never raises."""
    described = "\n".join(
        f"- {signal.source}: "
        + ("no current reading" if not signal.counts else ("yes" if signal.says else "no"))
        + f" ({signal.detail}"
        + (f", {signal.age:.0f}s old" if signal.age is not None else "")
        + ")"
        for signal in found
    )
    if unknown:
        described += f"\n- {unknown} face(s) seen that have not been identified"

    try:
        completion = client.call_with_fallback(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": described},
            ],
            job="aux",
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.1,
            **auxiliary.fallback_overrides("mind"),
        )
        answer = json.loads((completion.text or "").strip().strip("`").removeprefix("json"))
    except Exception as exc:
        log.info("presence judgement unavailable (%s); falling back to the sensors", exc)
        speaking = [signal for signal in found if signal.counts]
        return _arithmetic(found, speaking, disagree(found), unknown)

    who = str(answer.get("who") or "unknown")
    return Reading(
        present=bool(answer.get("present")),
        who=who if who in ("owner", "someone", "nobody", "unknown") else "unknown",
        confidence=max(0.0, min(float(answer.get("confidence") or 0.0), 1.0)),
        why=str(answer.get("why") or "").strip()[:200] or "No reason given.",
        judged=True,
    )
