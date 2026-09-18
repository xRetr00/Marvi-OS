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
    assert verdict.surface == "activity" and verdict.rule == "windows-busy"
    # Held, not dropped: it is offered again once the slideshow ends.
    assert "windows-busy" in WAITING_FOR


def test_an_alarm_still_gets_through() -> None:
    assert evaluate(ALARM, _world("you are presenting"), AWAKE, wanted="speak").surface == "speak"


def test_not_busy_changes_nothing() -> None:
    assert evaluate(REMINDER, _world(), AWAKE, wanted="speak").surface == "speak"


def test_the_windows_states_and_the_switch(monkeypatch) -> None:
    clock = {"now": 5_000.0}
    monkeypatch.setattr(focus.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(focus, "_busy_reason", "", raising=False)
    monkeypatch.setattr(focus, "_busy_at", 0.0, raising=False)
    monkeypatch.setattr(focus, "_notification_state", lambda: 4)
    monkeypatch.setenv(focus.BUSY_SETTING, "1")
    assert focus.windows_busy() == "you are presenting"

    # Windows drops the flag the instant a fullscreen app loses focus, and an
    # alt-tab emptied the waiting room into that gap: four held items spoken
    # mid-session on 16 September. Busy lingers; see `BUSY_SETTLES_AFTER`.
    monkeypatch.setattr(focus, "_notification_state", lambda: 5)  # QUNS_ACCEPTS_NOTIFICATIONS
    assert focus.windows_busy() == "you are presenting"
    clock["now"] += focus.BUSY_SETTLES_AFTER + 1
    assert focus.windows_busy() == ""

    monkeypatch.setattr(focus, "_notification_state", lambda: 2)
    monkeypatch.setenv(focus.BUSY_SETTING, "0")
    assert focus.windows_busy() == ""


# -- Focus Assist, read from state Windows does not document -------------------


def test_focus_assist_is_read_timidly(monkeypatch) -> None:
    """M11: a definite profile counts; everything else changes nothing.

    The state name resolves on the dev host and publishes zero bytes, which is
    what a machine that has never switched Focus Assist on looks like -- and is
    indistinguishable from a Windows build that moved it. So only a four-byte
    1 or 2 is believed.
    """
    monkeypatch.setenv(focus.FOCUS_ASSIST_SETTING, "1")

    def reading(status: int, payload: bytes):
        def query(_name, _a, _b, _stamp, buffer, size):
            for index, byte in enumerate(payload):
                buffer[index] = byte
            size._obj.value = len(payload)
            return status

        return query

    class FakeNtdll:
        def __init__(self, query):
            self.NtQueryWnfStateData = query

    import ctypes

    def with_reading(status, payload):
        monkeypatch.setattr(ctypes, "WinDLL", lambda _name: FakeNtdll(reading(status, payload)))
        return focus.focus_assist()

    assert "priority only" in with_reading(0, (1).to_bytes(4, "little"))
    assert "alarms only" in with_reading(0, (2).to_bytes(4, "little"))
    assert with_reading(0, (0).to_bytes(4, "little")) == ""  # off
    assert with_reading(0, b"") == ""  # nothing published: unknown
    assert with_reading(0, (7).to_bytes(4, "little")) == ""  # a value nobody has seen
    assert with_reading(0xC0000034, b"") == ""  # the name moved

    monkeypatch.setenv(focus.FOCUS_ASSIST_SETTING, "0")
    assert with_reading(0, (1).to_bytes(4, "little")) == ""  # switched off entirely
