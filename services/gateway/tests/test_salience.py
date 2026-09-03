"""Repetition decides what is worth thinking about, and arithmetic decides that.

The first stage of the Amygdala in PLAN.md -- deterministic salience ahead of
any optional model judgement -- measured into existence by what happened
without it. Over 946 real decisions the Mind spent 911,280 tokens, 97.4% of
those calls ended `silent`, and two event kinds were 90.1% of the entire spend:

    room:vision_sleep_state    11,447 of 12,135 events
    room:vision_visitor_seen

Four days running that exhausted the daily budget, and the exhausted budget
silenced 22 of the 23 real calendar events queued behind it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from marvi_gateway import salience
from marvi_gateway.journal import EventJournal
from marvi_gateway.mind import Mind
from marvi_gateway.policy import InitiativeSettings

NOON = datetime(2026, 9, 3, 12, tzinfo=UTC)


@pytest.fixture
def journal(tmp_path) -> EventJournal:
    return EventJournal(tmp_path / "journal.sqlite3")


def test_the_first_of_its_kind_is_worth_thinking_about() -> None:
    worth = salience.assess(0)
    assert worth.novel is True
    assert worth.worth_a_model is True
    assert worth.score == 1.0


def test_salience_decays_with_repetition() -> None:
    assert salience.assess(1).score == pytest.approx(0.5)
    assert salience.assess(9).score == pytest.approx(0.1)
    # The forty-seventh flap of a sleep sensor.
    assert salience.assess(46).score < 0.03


def test_a_flapping_sensor_stops_buying_model_calls() -> None:
    assert salience.assess(0).worth_a_model is True
    assert salience.assess(1).worth_a_model is True
    # Two occurrences are enough to see a state change confirmed. The third is
    # the sensor talking to itself.
    assert salience.assess(2).worth_a_model is False
    assert salience.assess(100).worth_a_model is False


def test_repetition_never_suppresses_something_urgent() -> None:
    """An alarm that goes off every morning is repetitive by design."""
    worth = salience.assess(500, urgent=True)
    assert worth.score == salience.URGENT_FLOOR
    assert worth.worth_a_model is True


def test_the_score_never_reads_the_event_text() -> None:
    """PLAN.md: emotional wording must not raise authority.

    `assess` takes a count and a boolean. There is no argument through which
    the content of an untrusted event could reach it.
    """
    import inspect

    taken = set(inspect.signature(salience.assess).parameters)
    assert taken == {"repeats", "urgent"}


def test_the_journal_counts_a_kind_rather_than_a_fingerprint(journal) -> None:
    """The flood was near-identical, not identical.

    The journal already collapses byte-identical events. What cost 911,280
    tokens was one sensor with a different sentence each time -- "Awake",
    "Sleep state changed", "Awake" -- so counting has to be by kind.
    """
    for text in ("Awake", "Sleep state changed", "Awake again"):
        journal.append("room", "vision_sleep_state", text, trusted=True)
    journal.append("room", "light_changed", "Light on", trusted=True)

    since = datetime.now(UTC) - timedelta(hours=1)
    assert journal.seen_recently("room", "vision_sleep_state", since) == 3
    assert journal.seen_recently("room", "light_changed", since) == 1
    assert journal.seen_recently("room", "nothing_like_this", since) == 0


def test_a_burst_costs_at_most_two_model_calls(journal) -> None:
    """The whole point, end to end.

    Ten events of one repetitive kind used to be ten model calls. The measured
    cost of that pattern was roughly nine hundred tokens each.
    """
    for n in range(10):
        journal.append("room", "light_changed", f"Light event {n}", trusted=True)

    calls: list[str] = []

    def deliberate(event, verdict):
        calls.append(event["summary"])
        return ("island", "", 900)

    mind = Mind(journal, settings=InitiativeSettings(), deliberate=deliberate)
    mind.tick(now=NOON)

    assert len(calls) <= 2, f"a repetitive burst bought {len(calls)} model calls"


def test_an_urgent_burst_still_gets_thought_about(journal) -> None:
    for n in range(4):
        journal.append("schedule", "insistent_reminder", f"Alarm {n}", trusted=True)

    calls: list[str] = []

    def deliberate(event, verdict):
        calls.append(event["summary"])
        return ("speak", "", 100)

    mind = Mind(journal, settings=InitiativeSettings(), deliberate=deliberate)
    mind.tick(now=NOON)

    assert calls, "repetition silenced something the policy would speak"


def test_a_repetitive_event_is_still_recorded(journal) -> None:
    """Recorded and inspectable; simply not reasoned about.

    Suppressing the *record* would trade a token problem for a blindness
    problem, and the decision log is how anyone answers "why did Marvi not say
    anything".
    """
    for n in range(6):
        journal.append("room", "light_changed", f"Light {n}", trusted=True)

    mind = Mind(journal, settings=InitiativeSettings(), deliberate=lambda e, v: ("island", "", 900))
    mind.tick(now=NOON)

    decisions = mind.why()
    assert len(decisions) == 6, "a repetitive event vanished instead of being recorded"
    assert all(d["surface"] != "speak" for d in decisions)
