"""What Marvi is doing right now, for the Voice page.

The page could name the models and nothing else, so a turn that paused for four
seconds looked the same whether she was searching the web or had simply
stopped. Chat has had a tool stack under every answer the whole time.
"""

from __future__ import annotations

from marvi_gateway import calendarview
from marvi_gateway.voiceactivity import Activity


def test_a_call_is_running_until_it_reports_otherwise() -> None:
    live = Activity()
    call = live.began("web_search", {"query": "fc 26"})

    state = live.state()

    assert state["running"] == 1
    assert state["calls"][0]["tool"] == "web_search"
    assert state["calls"][0]["arguments"] == {"query": "fc 26"}
    assert call


def test_a_finished_call_carries_how_long_it_took() -> None:
    live = Activity()
    call = live.began("room_state")
    live.ended(call, "ok", "light on at 70")

    call_row = live.state()["calls"][0]

    assert call_row["outcome"] == "ok"
    assert call_row["ms"] >= 0
    assert live.state()["running"] == 0


def test_a_call_nobody_finished_is_abandoned_not_running(monkeypatch) -> None:
    """Nothing reports completion for a tool the Agent gave up on, and a
    spinner that never stops reads as the page being broken."""
    import marvi_gateway.voiceactivity as module

    live = Activity()
    live.began("terminal_run")
    clock = [module.time.time() + module.RUNNING_FOR + 1]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])

    assert live.state()["calls"][0]["outcome"] == "abandoned"


def test_the_agent_may_bring_its_own_id() -> None:
    """Handing one back means the Agent waits for this reply before running
    the tool, which put a network round trip in front of every call."""
    live = Activity()

    assert live.began("web_search", {}, "mine-1") == "mine-1"
    live.ended("mine-1", "failed", "no network")
    assert live.state()["calls"][0]["outcome"] == "failed"


def test_a_new_session_starts_empty() -> None:
    live = Activity()
    live.began("web_search")
    live.counted(400, 16000, 2)

    live.cleared()

    assert live.state()["calls"] == []
    assert live.state()["context"] == {"used": 0, "window": 0, "turns": 0}


def test_only_a_session_worth_is_kept() -> None:
    live = Activity(keep=3)
    for index in range(6):
        live.began(f"tool_{index}")

    calls = live.state()["calls"]

    assert len(calls) == 3
    # Newest first: the page reads downward from what just happened.
    assert calls[0]["tool"] == "tool_5"


def test_the_calendar_payload_becomes_rows_a_card_can_draw() -> None:
    payload = {
        "items": [
            {
                "id": "b",
                "summary": "Later",
                "start": {"dateTime": "2026-09-02T10:00:00+03:00"},
                "end": {"dateTime": "2026-09-02T11:00:00+03:00"},
            },
            {"id": "a", "summary": "Sooner", "start": {"date": "2026-09-01"}},
        ]
    }

    rows = calendarview.upcoming(payload)

    assert [row["id"] for row in rows] == ["a", "b"], "not sorted by when they start"
    assert rows[0]["all_day"] is True
    assert rows[1]["all_day"] is False


def test_an_event_with_no_readable_title_says_busy() -> None:
    """Google omits the summary for events the user cannot see the details of,
    and "(busy)" is what the calendar itself shows there."""
    rows = calendarview.upcoming({"items": [{"id": "x", "start": {"date": "2026-09-01"}}]})

    assert rows[0]["title"] == "(busy)"


def test_a_shape_it_has_not_seen_returns_nothing_rather_than_raising() -> None:
    """A card must not take the page down over an API that moved."""
    assert calendarview.upcoming({"unexpected": True}) == []
    assert calendarview.upcoming(None) == []
