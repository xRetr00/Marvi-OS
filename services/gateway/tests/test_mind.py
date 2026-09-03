"""The proactivity contract and the mind turn.

These tests are mostly about restraint: the interesting behaviour is Marvi
choosing to stay quiet, and being able to say which rule made it do so.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from marvi_gateway.journal import DEDUPE_WINDOW_SECONDS, EventJournal
from marvi_gateway.memory import MemoryStore
from marvi_gateway.mind import Mind
from marvi_gateway.policy import (
    InitiativeSettings,
    WorldState,
    evaluate,
)

NOON = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def alarm(trusted=True):
    return {"source": "room", "kind": "alarm_started", "summary": "Alarm", "trusted": trusted,
            "payload": {}, "id": 1}


def email(trusted=False):
    return {"source": "accounts", "kind": "email", "summary": "Email: hi", "trusted": trusted,
            "payload": {}, "id": 2}


@pytest.fixture
def journal(tmp_path):
    j = EventJournal(tmp_path / "journal.sqlite3")
    yield j
    j.close()


# -- journal ----------------------------------------------------------------


def test_the_same_event_twice_is_one_event(journal) -> None:
    first = journal.append("accounts", "email", "Lunch?", {"id": "m-1"})
    second = journal.append("accounts", "email", "Lunch?", {"id": "m-1"})

    assert first is not None
    assert second is None
    assert len(journal.pending()) == 1


def test_the_same_event_is_accepted_again_after_the_window(journal) -> None:
    journal.append("room", "mode_changed", "focus", now=NOON)
    later = journal.append(
        "room", "mode_changed", "focus",
        now=NOON + timedelta(seconds=DEDUPE_WINDOW_SECONDS + 1),
    )
    assert later is not None


def test_events_carry_provenance_and_trust(journal) -> None:
    journal.append("accounts", "email", "hi", {"id": "x"}, trusted=False)
    event = journal.pending()[0]
    assert event["trusted"] is False
    assert event["source"] == "accounts"


def test_processed_events_leave_the_queue(journal) -> None:
    event_id = journal.append("room", "mode_changed", "focus")
    journal.mark_processed(event_id, decision_id=None)
    assert journal.pending() == []
    assert journal.count_pending() == 0


# -- policy: the five conditions --------------------------------------------


def world(**kwargs):
    return WorldState(now=kwargs.pop("now", NOON), **kwargs)


def test_a_paused_user_wins_over_everything() -> None:
    verdict = evaluate(alarm(), world(), InitiativeSettings(paused=True), wanted="speak")
    assert verdict.allow is False
    assert verdict.rule == "initiative-paused"


def test_untrusted_content_can_inform_but_never_propose() -> None:
    settings = InitiativeSettings()
    settings.surface_ceiling["accounts:email"] = "propose"

    verdict = evaluate(email(trusted=False), world(), settings, wanted="propose")

    # An email may reach the Island; it may never be the reason Marvi acts.
    assert verdict.surface in ("island", "activity")
    assert verdict.surface != "propose"


def test_trusted_events_may_reach_their_ceiling() -> None:
    verdict = evaluate(alarm(trusted=True), world(), wanted="speak")
    assert verdict.allow is True
    assert verdict.surface == "speak"
    assert verdict.rule == "allowed"


def test_smart_room_delivery_events_may_speak() -> None:
    for kind in ("alarm_requested", "room_welcome", "visitor_report"):
        event = {
            "source": "room", "kind": kind, "summary": kind,
            "trusted": True, "payload": {}, "id": kind,
        }
        assert evaluate(event, world(), wanted="speak").surface == "speak"


def test_marvi_does_not_talk_over_a_live_conversation() -> None:
    verdict = evaluate(alarm(), world(conversation_active=True), wanted="speak")
    assert verdict.surface == "activity"
    assert verdict.rule == "conversation-active"


def test_a_chatty_source_is_throttled_by_cooldown() -> None:
    recent = world(last_surfaced=NOON - timedelta(minutes=2))
    verdict = evaluate(alarm(), recent, wanted="speak")
    assert verdict.rule == "cooldown"
    assert verdict.surface == "activity"


def test_cooldown_expires() -> None:
    old = world(last_surfaced=NOON - timedelta(hours=2))
    assert evaluate(alarm(), old, wanted="speak").rule == "allowed"


def test_quiet_hours_downgrade_speech_to_something_glanceable() -> None:
    settings = InitiativeSettings(quiet_start=0, quiet_end=23)
    verdict = evaluate(alarm(), world(), settings, wanted="speak")
    assert verdict.rule == "quiet-hours"
    assert verdict.surface == "island"


def test_speaking_to_an_empty_room_is_downgraded() -> None:
    verdict = evaluate(alarm(), world(present=False), wanted="speak")
    assert verdict.rule == "nobody-present"
    assert verdict.surface == "island"


def test_an_exhausted_budget_means_silence() -> None:
    verdict = evaluate(alarm(), world(tokens_today=10_000_000), wanted="speak")
    assert verdict.allow is False
    assert verdict.rule == "daily-budget"


def test_an_unknown_event_type_is_never_loud() -> None:
    unknown = {"source": "mystery", "kind": "thing", "summary": "?", "trusted": True, "payload": {}}
    assert evaluate(unknown, world(), wanted="speak").surface == "activity"


# -- the mind turn ----------------------------------------------------------


def test_an_idle_tick_decides_nothing_and_costs_nothing(journal) -> None:
    result = Mind(journal).tick(now=NOON)
    assert result == {"considered": 0, "decisions": [], "surfaced": []}
    assert journal.decisions() == []


def test_every_decision_records_the_rule_that_caused_it(journal) -> None:
    journal.append("room", "alarm_started", "Alarm going off", trusted=True)
    mind = Mind(journal)
    mind.tick(now=NOON)

    decision = mind.why()[0]
    assert decision["surface"] == "speak"
    assert decision["rule"] == "allowed"
    assert decision["trigger"] == "Alarm going off"
    assert decision["provider"] == "deterministic"


def test_silence_is_explained_too(journal) -> None:
    journal.append("room", "alarm_started", "Alarm", trusted=True)
    mind = Mind(journal, settings=InitiativeSettings(paused=True))
    result = mind.tick(now=NOON)

    assert result["surfaced"] == []
    assert mind.why()[0]["rule"] == "initiative-paused"


def test_an_event_is_only_decided_once(journal) -> None:
    journal.append("room", "alarm_started", "Alarm", trusted=True)
    mind = Mind(journal)

    first = mind.tick(now=NOON)
    second = mind.tick(now=NOON)

    assert first["considered"] == 1
    assert second["considered"] == 0


def test_remembered_events_keep_their_trust_level(journal, tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    try:
        journal.append("memory", "reflection", "A pattern", trusted=False)
        Mind(journal, memory=memory).tick(now=NOON)

        entry = memory.search("pattern")[0]
        assert entry["trusted"] is False
        assert "UNTRUSTED" in entry["body"]
    finally:
        memory.close()


def test_an_llm_may_make_a_decision_quieter_but_never_louder(journal) -> None:
    journal.append("room", "alarm_started", "Alarm", trusted=True)

    def louder(event, verdict):
        return "propose", "let me act", 0.01

    def quieter(event, verdict):
        return "activity", "not worth interrupting", 0.01

    loud_mind = Mind(journal, deliberate=louder)
    loud_mind.tick(now=NOON)
    assert loud_mind.why()[0]["surface"] == "speak"  # capped at the policy verdict

    journal.append("room", "alarm_started", "Alarm again", trusted=True)
    quiet_mind = Mind(journal, deliberate=quieter)
    quiet_mind.tick(now=NOON + timedelta(hours=3))
    assert quiet_mind.why()[0]["surface"] == "activity"


def test_llm_tokens_count_against_the_daily_budget(journal) -> None:
    journal.append("room", "alarm_started", "Alarm", trusted=True)
    mind = Mind(journal, deliberate=lambda e, v: ("island", "", 250))
    mind.tick(now=NOON)

    assert journal.tokens_since(NOON - timedelta(hours=1)) == 250


def test_budget_exhaustion_silences_later_events_in_the_same_day(journal) -> None:
    """Three different sources, because cooldown is per source and kind.

    This used to append the same `room:alarm_started` three times, and it
    passed for the wrong reason: the second event was capped to `activity` by
    the cooldown rule and *still* bought a model call, which is what pushed the
    total over the budget. That waste is now refused -- deliberation only runs
    where it could change the outcome -- so exhausting the budget takes three
    events that genuinely deliberate.

    The waste was not hypothetical. On the owner's machine it was 85% of the
    mind's entire token spend.
    """
    journal.append("room", "alarm_started", "Alarm", trusted=True)
    journal.append("schedule", "reminder", "Reminder", trusted=True)
    journal.append("room", "visitor_report", "Someone at the door", trusted=True)
    mind = Mind(journal, settings=InitiativeSettings(daily_token_budget=300),
                deliberate=lambda e, v: ("island", "", 200))
    mind.tick(now=NOON)

    rules = [d["rule"] for d in mind.why()]
    assert "daily-budget" in rules, rules


def test_the_quietest_visible_surface_is_not_worth_a_model_call(journal) -> None:
    """An event the policy has already capped at `activity` cannot get louder.

    The model may only make a decision quieter, so the loudest thing it can
    propose for one of these is what is already going to happen -- and the only
    other option is silence. Measured over 200 real decisions, 102,021 tokens
    went on 122 such calls, 85% of them three room sensors that every time
    ended silent, and the exhausted budget then silenced 22 of 23 real calendar
    events behind them.
    """
    journal.append("room", "light_changed", "Light on", trusted=True)
    calls: list[str] = []

    def deliberate(event, verdict):
        calls.append(event["kind"])
        return ("activity", "", 900)

    mind = Mind(journal, settings=InitiativeSettings(), deliberate=deliberate)
    mind.tick(now=NOON)

    assert calls == [], "a model was paid to confirm a floor it cannot move off"
    assert [d["tokens"] for d in mind.why()] == [0]
