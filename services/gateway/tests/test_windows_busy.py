"""When Windows says not to interrupt, Marvi does not either."""

from __future__ import annotations

from datetime import UTC, datetime

from marvi_gateway import focus
from marvi_gateway.pending import WAITING_FOR
from marvi_gateway.policy import InitiativeSettings, WorldState, evaluate

REMINDER = {"source": "schedule", "kind": "reminder", "trusted": True}
ALARM = {"source": "schedule", "kind": "insistent_reminder", "trusted": True}
AWAKE = InitiativeSettings(quiet_enabled=False)


def _world(busy: str = "") -> WorldState:
    return WorldState(now=datetime(2026, 9, 16, 14, 0, tzinfo=UTC), busy=busy)


def test_a_presentation_holds_speech_and_the_island() -> None:
    verdict = evaluate(REMINDER, _world("you are presenting"), AWAKE, wanted="speak")
    assert verdict.surface == "activity" and verdict.reason == "windows-busy"
    # Held, not dropped: it is offered again once the slideshow ends.
    assert "windows-busy" in WAITING_FOR


def test_an_alarm_still_gets_through() -> None:
    assert evaluate(ALARM, _world("you are presenting"), AWAKE, wanted="speak").surface == "speak"


def test_not_busy_changes_nothing() -> None:
    assert evaluate(REMINDER, _world(), AWAKE, wanted="speak").surface == "speak"


def test_the_windows_states_and_the_switch(monkeypatch) -> None:
    monkeypatch.setattr(focus, "_notification_state", lambda: 4)
    monkeypatch.setenv(focus.BUSY_SETTING, "1")
    assert focus.windows_busy() == "you are presenting"
    monkeypatch.setattr(focus, "_notification_state", lambda: 5)  # QUNS_ACCEPTS_NOTIFICATIONS
    assert focus.windows_busy() == ""
    monkeypatch.setattr(focus, "_notification_state", lambda: 2)
    monkeypatch.setenv(focus.BUSY_SETTING, "0")
    assert focus.windows_busy() == ""
