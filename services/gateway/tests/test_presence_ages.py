"""Timestamps the room actually sends, and what happens when one goes stale.

`_age` understood epoch numbers. The sidecar sends ISO strings for every
timestamp in the room state, so every age came back None -- and a None age is
never stale, which turned the whole staleness rule off for all four signals
without anything reporting a fault.

What it cost: OwnTracks publishes a `transition` only when you cross a
boundary, so a missed one leaves the last edge standing. The live room state
said `home: true` from a geofence event **thirteen days old**, and presence
weighed it as a current reading.
"""

from __future__ import annotations

import time

from marvi_gateway import presence
from marvi_gateway.presence import STALE_AFTER, _age, signals


def test_iso_timestamps_are_measured() -> None:
    # The shape the sidecar actually sends. `now` is read here rather than at
    # import: in a full suite run the module is imported minutes before this
    # executes, and a captured clock makes a fresh stamp look like the future.
    from datetime import UTC, datetime, timedelta

    now = time.time()
    recent = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    assert 20 < (_age(recent, now) or 0) < 60


def test_epoch_timestamps_still_work() -> None:
    now = time.time()
    assert 55 < (_age(now - 60, now) or 0) < 65


def test_nonsense_is_unknown_rather_than_now() -> None:
    now = time.time()
    for value in (None, "", "not a time", 12345, True, False, [], {}):
        assert _age(value, now) is None, f"{value!r} was read as a timestamp"


def test_a_thirteen_day_old_geofence_stops_counting() -> None:
    """The real one, from the owner's live room state.

    OwnTracks had not sent a transition in thirteen days, and Marvi asserted
    `home: true` the whole time off that one edge.
    """
    state = {
        "location": {
            "home": True,
            "zone": "home",
            "source": "owntracks",
            "last_geofence_at": "2026-08-24T21:46:54.084802+00:00",
        }
    }
    phone = next(one for one in signals(state, now=time.time()) if one.source == "phone")
    assert phone.age is not None and phone.age > STALE_AFTER
    assert phone.stale is True
    assert phone.counts is False, "a fortnight-old geofence was weighed as current"


def test_a_fresh_geofence_still_counts() -> None:
    from datetime import UTC, datetime

    state = {
        "location": {
            "home": True,
            "zone": "home",
            "source": "owntracks",
            "last_geofence_at": datetime.now(UTC).isoformat(),
        }
    }
    phone = next(one for one in signals(state, now=time.time()) if one.source == "phone")
    assert phone.stale is False
    assert phone.counts is True


def test_a_stale_phone_does_not_drag_the_others_into_a_model_call() -> None:
    """Three live sensors that agree is arithmetic, not a judgement call.

    Before the ages were measured the stale phone was a fourth opinion, so the
    signals "disagreed" and every read bought a model call to resolve an
    ambiguity that was thirteen days old.
    """
    from datetime import UTC, datetime

    fresh = datetime.now(UTC).isoformat()
    # The keys the sidecar actually uses: `occupied`/`last_seen` for mmWave and
    # `person_count` for the camera.
    state = {
        "mmwave": {"occupied": True, "last_seen": fresh},
        "vision": {"person_count": 1, "owner_visible": True, "last_inference_at": fresh},
        "presence": {"detected": True, "source": "ble", "last_seen": fresh, "confidence": 0.7},
        "location": {
            "home": False,
            "zone": "away",
            "source": "owntracks",
            "last_geofence_at": "2026-08-24T21:46:54+00:00",
        },
    }
    found = signals(state, now=time.time())
    assert presence.disagree(found) is False, "a stale signal still caused a disagreement"
