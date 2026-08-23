"""Who is in the room, when the sensors disagree.

The deterministic path is the one that decides almost every case, so it is the
one with the tests. The model is asked only on conflict, and what matters there
is that it is asked at all, that a bad answer cannot get through, and that its
absence costs nothing.
"""

from __future__ import annotations

import json
import time

from marvi_gateway import presence


def room(**blocks) -> dict:
    """A room state with only the blocks a test cares about."""
    now = time.time()
    base = {
        "mmwave": {},
        "vision": {},
        "location": {},
        "presence": {},
    }
    for key, value in blocks.items():
        base[key] = value
    base.setdefault("_now", now)
    base.pop("_now")
    return base


# -- reading the sensors ------------------------------------------------------


def test_a_sensor_with_no_reading_has_no_opinion() -> None:
    """The distinction the whole module exists for.

    A camera reporting "No module named cv2" is not a camera reporting an
    empty room, and treating those the same is how "nobody is here" got said
    about a room with somebody in it.
    """
    now = time.time()
    found = {
        signal.source: signal
        for signal in presence.signals(
            room(vision={"error": "No module named 'cv2'", "person_count": 0}), now
        )
    }

    assert found["camera"].says is None
    assert found["camera"].counts is False


def test_a_stale_reading_is_not_evidence() -> None:
    """A sensor that stopped talking an hour ago is evidence about the sensor."""
    now = time.time()
    found = {
        signal.source: signal
        for signal in presence.signals(
            room(mmwave={"occupied": True, "last_seen": now - presence.STALE_AFTER - 60}), now
        )
    }

    assert found["mmwave"].stale is True
    assert found["mmwave"].counts is False


def test_agreement_needs_no_model() -> None:
    """Almost every poll. A model call per poll would be slow and expensive,
    and there is nothing to weigh when nothing disagrees."""
    now = time.time()
    state = room(
        mmwave={"occupied": True, "last_seen": now - 5},
        vision={"person_count": 1, "owner_visible": True, "last_inference_at": now - 2},
    )

    class Loud:
        def call_with_fallback(self, *_a, **_k):
            raise AssertionError("a model was asked about sensors that agree")

    reading = presence.read(state, client=Loud(), now=now)

    assert reading.present is True
    assert reading.who == "owner"
    assert reading.judged is False


def test_disagreement_is_what_summons_a_model() -> None:
    """The case in the report: mmWave sees nobody, the camera sees somebody."""
    now = time.time()
    state = room(
        mmwave={"occupied": False, "last_seen": now - 5},
        vision={"person_count": 1, "owner_visible": True, "last_inference_at": now - 2},
    )
    asked: list[str] = []

    class Judge:
        def call_with_fallback(self, messages, **_k):
            asked.append(messages[-1]["content"])

            class Answer:
                text = json.dumps(
                    {
                        "present": True,
                        "who": "owner",
                        "confidence": 0.8,
                        "why": "The camera recognised them sitting still.",
                    }
                )

            return Answer()

    reading = presence.read(state, client=Judge(), now=now)

    assert reading.judged is True
    assert reading.present is True and reading.who == "owner"
    # Every sensor is described to it, including the ones with no reading.
    assert "mmwave" in asked[0] and "camera" in asked[0]


def test_an_unknown_face_summons_a_model_even_when_nothing_disagrees() -> None:
    """A visitor nobody has met is exactly the judgement call."""
    now = time.time()
    state = room(
        mmwave={"occupied": True, "last_seen": now - 5},
        vision={"person_count": 1, "pending_visitors": 1, "last_inference_at": now - 2},
    )

    class Judge:
        def call_with_fallback(self, messages, **_k):
            assert "not been identified" in messages[-1]["content"]

            class Answer:
                text = '{"present": true, "who": "someone", "confidence": 0.7, "why": "A face."}'

            return Answer()

    assert presence.read(state, client=Judge(), now=now).judged is True


def test_a_model_that_fails_falls_back_to_the_sensors() -> None:
    """This runs on a poll. A provider cooling down must not stop the room
    having an opinion."""
    now = time.time()
    state = room(
        mmwave={"occupied": False, "last_seen": now - 5},
        vision={"person_count": 1, "last_inference_at": now - 2},
    )

    class Broken:
        def call_with_fallback(self, *_a, **_k):
            raise RuntimeError("every provider is cooling down")

    reading = presence.read(state, client=Broken(), now=now)

    assert reading.judged is False
    assert "disagree" in reading.why


def test_a_nonsense_verdict_cannot_get_through() -> None:
    now = time.time()
    state = room(
        mmwave={"occupied": False, "last_seen": now - 5},
        vision={"person_count": 1, "last_inference_at": now - 2},
    )

    class Wild:
        def call_with_fallback(self, *_a, **_k):
            class Answer:
                text = '{"present": true, "who": "the postman", "confidence": 9.5, "why": ""}'

            return Answer()

    reading = presence.read(state, client=Wild(), now=now)

    assert reading.who == "unknown"
    assert reading.confidence <= 1.0
    assert reading.why


def test_no_reading_at_all_is_unknown_rather_than_empty() -> None:
    """"Nobody is here" and "nothing is reporting" are different answers and
    only one of them is safe to act on."""
    reading = presence.read(room(), client=None)

    assert reading.present is False
    assert reading.who == "unknown"
    assert reading.confidence == 0.0


# -- what a wrong answer leaves behind ----------------------------------------


def test_the_reading_carries_every_signal_that_went_into_it() -> None:
    """The reason this module exists at all: "presence: false" told nobody
    which sensor said so, how old the reading was, or whether anything
    disagreed with it."""
    now = time.time()
    reading = presence.read(
        room(
            mmwave={"occupied": False, "last_seen": now - 5},
            vision={"person_count": 2, "last_inference_at": now - 1},
        ),
        client=None,
        now=now,
    )

    described = reading.as_dict()
    sources = {signal["source"] for signal in described["signals"]}

    assert sources == {"mmwave", "camera", "phone", "bluetooth"}
    for signal in described["signals"]:
        assert set(signal) >= {"source", "says", "detail", "age", "confidence", "stale"}
    assert described["why"]
