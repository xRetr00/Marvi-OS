"""One recurring event is one memory, not one per occurrence.

Recorded from a real failure. A yearly birthday was ingested as 23 separate
occurrences dated 13 August 2002 through 13 August 2071, each journalled as
news and each written to memory as an episodic fact. Reflection and dreaming
then generalised the pile into two durable beliefs -- "Recurs: seen 23 times"
and "a recurring birthday event on August 13th spanning from 2031 to 2071, with
gaps in 2041-2047" -- so Marvi had learned something about the owner that was
an ingest artefact. Deliberating about them also spent the mind's daily token
budget, which then silenced 22 of the 23 real calendar events behind them.

Two independent guards, because either alone leaves a hole:

* a horizon on the calendar fetch, which stops a *yearly* event walking to 2071
* recurrence identity, which stops a *daily* event producing thirty memories
  inside that horizon
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from marvi_gateway.ingest import _normalise_calendar
from marvi_gateway.memory import MemoryStore


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore(pathlib.Path(tempfile.mkdtemp()) / "memory.sqlite3")


def test_a_recurring_instance_carries_its_series() -> None:
    """Google gives the identity for free: `<baseId>_<YYYYMMDD>`."""
    item = _normalise_calendar(
        {"id": "mc7d6kvf9ajl2vvqsln23e7ajc_20310813", "summary": "Happy birthday!"}
    )
    assert item is not None
    assert item.series == "composio:googlecalendar:mc7d6kvf9ajl2vvqsln23e7ajc"


def test_a_timed_occurrence_is_recognised_too() -> None:
    item = _normalise_calendar({"id": "standup_20260903T090000Z", "summary": "Standup"})
    assert item is not None
    assert item.series == "composio:googlecalendar:standup"


def test_a_one_off_event_has_no_series() -> None:
    # A single event must keep appending: two distinct events are two memories.
    item = _normalise_calendar({"id": "just-one-event", "summary": "Dentist"})
    assert item is not None
    assert item.series == ""


def test_occurrences_of_one_series_collapse_to_one_memory(store: MemoryStore) -> None:
    """The birthday failure, in miniature.

    Thirty daily occurrences are thirty renderings of one thing, not thirty
    moments -- and the store deliberately never supersedes episodic memories,
    which is right for moments and was what let this happen.
    """
    series = "composio:googlecalendar:standup"
    written = [
        store.remember(
            "Event: Standup",
            f"Starts 2026-09-{day:02d}",
            kind="episodic",
            source="cal",
            trusted=False,
            series=series,
        )
        for day in range(1, 31)
    ]

    assert len(set(written)) == 1, "each occurrence created a new memory"
    assert len(store.recent(limit=50)) == 1
    # And it holds the newest occurrence, not the first.
    assert "2026-09-30" in store.recent(limit=1)[0]["body"]


def test_different_series_stay_separate(store: MemoryStore) -> None:
    store.remember("Event: Standup", "a", kind="episodic", source="c", series="s:standup")
    store.remember("Event: Gym", "b", kind="episodic", source="c", series="s:gym")
    assert len(store.recent(limit=10)) == 2


def test_moments_without_a_series_still_accumulate(store: MemoryStore) -> None:
    """The existing rule, unchanged: two moments are not a contradiction."""
    store.remember("Talked about the graph", "once", kind="episodic", source="marvi")
    store.remember("Talked about the graph", "again", kind="episodic", source="marvi")
    assert len(store.recent(limit=10)) == 2


def test_the_calendar_fetch_is_bounded_at_both_ends() -> None:
    """The horizon that stops a yearly event walking to 2071.

    `singleEvents` expands a recurring event into one item per occurrence --
    which is what makes "what is on this week" answerable, and what made a
    birthday walk forward forever with no upper bound.
    """
    from datetime import UTC, datetime

    from marvi_gateway.ingest import _calendar_ceiling, _calendar_floor

    floor = datetime.fromisoformat(_calendar_floor("").replace("Z", "+00:00"))
    ceiling = datetime.fromisoformat(_calendar_ceiling().replace("Z", "+00:00"))
    now = datetime.now(UTC)

    assert floor < now < ceiling
    assert (ceiling - now).days <= 31
    assert (now - floor).days <= 2
    # A cursor is honoured as the floor, so incremental sync still works.
    assert _calendar_floor("2026-09-01T00:00:00Z") == "2026-09-01T00:00:00Z"
