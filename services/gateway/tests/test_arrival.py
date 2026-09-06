"""Who walked in, and how sure she is allowed to be.

Every case here is one the owner described, in the order the signals actually
arrive. The point of the file is the disagreements: "all four say yes" is an
`and`, not judgement, and what makes it judgement is what happens when the
sensor that identifies a person is the one that is missing.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from marvi_gateway import arrival, presence
from marvi_gateway.arrival import judge, phone_can_be_believed, where

FRESH = datetime.now(UTC).isoformat()
STALE = "2026-08-24T21:46:54+00:00"


def _room(*, mmwave=None, people=None, owner=False, unknown=0, ble=None, location=None):
    state: dict = {}
    if mmwave is not None:
        state["mmwave"] = {"occupied": mmwave, "last_seen": FRESH}
    if people is not None:
        state["vision"] = {
            "person_count": people,
            "owner_visible": owner,
            "unknown_count": unknown,
            "last_inference_at": FRESH,
        }
    if ble is not None:
        state["presence"] = {
            "detected": ble, "source": "ble", "last_seen": FRESH, "confidence": 0.7
        }
    state["location"] = location or {}
    return state


def _judge(state):
    return judge(state, presence.signals(state, now=time.time()))


# -- the chain, in order ----------------------------------------------------


def test_owntracks_entering_home_is_readiness_not_arrival() -> None:
    """The minutes of warning while the car is still moving.

    Worth putting the light on for. Not worth claiming somebody has arrived:
    a phone crossing a line is how you greet an empty room.
    """
    assert arrival.expecting({"home": True, "zone": "home"}) is True
    assert arrival.expecting({"home": False, "zone": "bakery"}) is False


def test_the_camera_settles_it_on_its_own() -> None:
    # No mmWave, no phone. A face is a face.
    who = _judge(_room(people=1, owner=True))
    assert who.verdict == "owner"
    assert who.confidence > 0.9


def test_a_face_it_does_not_know_is_a_stranger() -> None:
    who = _judge(_room(mmwave=True, people=1, owner=False, unknown=1))
    assert who.verdict == "stranger"
    assert who.watch is True, "did not start watching an unrecognised face"


def test_no_camera_but_the_phone_is_here_hedges() -> None:
    """Camera offline, phone present: welcome, and say it is not certain."""
    who = _judge(_room(mmwave=True, ble=True, location={"home": True, "regions": ["home"]}))
    assert who.verdict == "probably_owner"
    assert who.is_owner is True
    assert "sure" in who.say.lower()


# -- the edge cases, which are the point ------------------------------------


def test_a_dying_phone_explains_its_own_silence() -> None:
    """Somebody is here, no phone, and the battery was nearly flat.

    The likeliest reason a dead phone stopped advertising is that it is dead,
    and turning its owner into an intruder over it is the wrong answer.
    """
    who = _judge(
        _room(
            mmwave=True,
            ble=False,
            location={"home": True, "regions": ["home"], "battery_percent": 8, "battery_state": 1},
        )
    )
    assert who.verdict == "probably_owner"
    assert "quiet" in who.say.lower()
    assert who.watch is False, "photographed the owner over a flat battery"


def test_a_healthy_phone_somewhere_else_means_a_stranger() -> None:
    """Battery fine, phone at the bakery, and something is moving in the room."""
    who = _judge(
        _room(
            mmwave=True,
            ble=False,
            location={
                "home": False, "zone": "bakery", "regions": ["bakery"],
                "battery_percent": 84, "battery_state": 1,
            },
        )
    )
    assert who.verdict == "stranger"
    assert who.watch is True
    assert "not you" in who.say.lower()


def test_somebody_here_and_nothing_can_say_who_asks() -> None:
    # Phone at home but not advertising, battery healthy, no camera. Neither
    # alarming nor certain -- so she asks rather than guessing either way.
    who = _judge(
        _room(mmwave=True, ble=False, location={"home": True, "regions": ["home"], "battery_percent": 90})
    )
    assert who.verdict == "unsure"
    assert "check your phone" in who.say.lower()


def test_an_empty_room_is_not_a_stranger() -> None:
    who = _judge(_room(mmwave=False, ble=False, location={"home": True}))
    assert who.verdict == "nobody"


def test_no_working_sensor_says_unsure_not_nobody() -> None:
    """"Nobody" is a claim, and no working sensor is not in a position to make
    one. This is the distinction the whole presence module exists for."""
    who = _judge({"location": {}})
    assert who.verdict == "unsure"
    assert who.confidence == 0.0


def test_a_stale_signal_carries_no_opinion() -> None:
    # The thirteen-day-old geofence, again: aged out before it reaches here.
    state = _room(mmwave=True, ble=False, location={"home": True, "regions": ["home"]})
    state["presence"]["last_seen"] = STALE
    who = _judge(state)
    assert who.signals["phone"] is None


# -- regions ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ({"regions": ["home"]}, "home"),
        ({"regions": ["bakery"]}, "bakery"),
        # Level-triggered and self-healing: empty is "outside every region",
        # which is an answer rather than an absence of one.
        ({"regions": []}, "out"),
        # No `inregions` at all falls back to the last transition.
        ({"zone": "home"}, "home"),
        ({}, "unknown"),
    ],
)
def test_where_reads_regions_before_transitions(location, expected) -> None:
    assert where(location) == expected


@pytest.mark.parametrize(
    ("battery", "state", "believable"),
    [
        (90, 1, True),
        (8, 1, False),
        # Charging at 8% is a phone that is plugged in and fine.
        (8, 2, True),
        (None, None, True),
        ("nonsense", None, True),
    ],
)
def test_a_silent_phone_is_only_evidence_when_it_had_power(battery, state, believable) -> None:
    found, _why = phone_can_be_believed({"battery_percent": battery, "battery_state": state})
    assert found is believable


def test_a_phone_alone_in_an_empty_room_is_not_the_owner() -> None:
    """The documented failure, caught by running it against the real room.

    mmWave said nobody, the camera said nobody, and the phone was on the desk
    charging -- and the first version answered "probably the owner, welcome
    back". A phone is not a person; it is identity, not detection.
    """
    who = _judge(
        _room(mmwave=False, people=0, ble=True, location={"home": True, "regions": ["home"]})
    )
    assert who.verdict == "nobody", f"greeted a phone on a desk ({who.verdict})"


def test_a_phone_present_with_somebody_there_is_still_the_hedge() -> None:
    # The distinction that makes the rule above safe: with mmWave confirming a
    # person, the same phone becomes evidence of *who* it is.
    who = _judge(
        _room(mmwave=True, ble=True, location={"home": True, "regions": ["home"]})
    )
    assert who.verdict == "probably_owner"
