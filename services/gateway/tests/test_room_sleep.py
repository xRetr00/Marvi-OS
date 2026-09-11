"""Sleep mode, and the room's arrivals, as the speaking policy sees them.

From one night of the owner's real journal: sleep mode went on at 05:18 and
"Unidentified entered the room" was spoken at 05:30, 14:08 and 14:17 -- quiet
hours had ended, nothing else asked whether anybody was asleep, and every one
of those "arrivals" was him turning over under a blanket.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from marvi_gateway.app import _room_asleep
from marvi_gateway.pending import WAITING_FOR
from marvi_gateway.policy import InitiativeSettings, WorldState, evaluate
from marvi_gateway.room import is_notable

AWAKE_HOURS = InitiativeSettings(quiet_enabled=False)


def _world(**changes) -> WorldState:
    base = {
        "now": datetime(2026, 9, 11, 14, 8, tzinfo=UTC),
        "present": True,
        "conversation_active": False,
        "tokens_today": 0,
        "last_surfaced": None,
    }
    base.update(changes)
    return WorldState(**base)


def _entry(classification: str) -> dict:
    return {
        "source": "room",
        "kind": "room_entry",
        "trusted": True,
        "payload": {"classification": classification},
    }


def test_sleep_mode_keeps_her_quiet_after_quiet_hours_end() -> None:
    verdict = evaluate(_entry("unknown_visitor"), _world(asleep=True), AWAKE_HOURS, wanted="speak")

    assert verdict.surface == "island"
    assert verdict.rule == "asleep"
    assert "asleep" in WAITING_FOR, "held, and never offered again once he wakes"


def test_the_wake_alarm_still_wakes_him() -> None:
    # An alarm that cannot wake you is not an alarm.
    verdict = evaluate(
        {"source": "schedule", "kind": "insistent_reminder", "trusted": True},
        _world(asleep=True),
        AWAKE_HOURS,
        wanted="speak",
    )

    assert verdict.surface == "speak"


def test_the_owner_being_found_again_is_a_record_not_an_announcement() -> None:
    # "Owner entered the room" was spoken as "someone is in the room while you
    # are out". His real arrival speaks through `room_welcome`.
    verdict = evaluate(_entry("owner"), _world(), AWAKE_HOURS, wanted="speak")

    assert verdict.surface == "activity"


def test_a_guess_is_shown_and_a_phone_elsewhere_is_said() -> None:
    guess = evaluate(_entry("unidentified"), _world(), AWAKE_HOURS, wanted="speak")
    stranger = evaluate(_entry("unknown_visitor"), _world(), AWAKE_HOURS, wanted="speak")

    assert guess.surface == "island"
    assert stranger.surface == "speak"


def test_the_visitor_photographs_reach_the_popup() -> None:
    # `/room/events` returns notable events only, and the photographs were not
    # one -- so the popup that shows them had never once had anything to show.
    assert is_notable({"type": "visitor_photos", "photos": []})


def test_the_rooms_mode_is_read_into_the_snapshot() -> None:
    asleep = SimpleNamespace(state=lambda: {"state": {"modes": {"active_mode": "sleep"}}})
    awake = SimpleNamespace(state=lambda: {"state": {"modes": {"active_mode": "normal"}}})

    def broken():
        raise RuntimeError("room plugin is not running")

    assert _room_asleep(asleep) is True
    assert _room_asleep(awake) is False
    # Unknown is awake here: going silent because the plugin is down is worse.
    assert _room_asleep(SimpleNamespace(state=broken)) is False
