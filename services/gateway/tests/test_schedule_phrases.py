"""Times written the way people write them.

The parser took `30m`, `every 2h`, `07:30`, ISO and raw cron. "every day at
18:00" -- which is what somebody types when nobody has told them the grammar --
was an error, and so was every suggestion the new-job form offered. A form
whose own examples it rejects is worse than one with no examples.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from marvi_gateway.schedule import ScheduleError, parse_when

#: A Sunday afternoon, so "tomorrow" and "every weekday" both have a real answer.
NOW = datetime(2026, 9, 6, 15, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "expression"),
    [
        ("every day at 18:00", "0 18 * * *"),
        ("every day at 9am", "0 9 * * *"),
        ("every day at 9pm", "0 21 * * *"),
        ("every weekday at 09:00", "0 9 * * 1-5"),
        ("every weekend at 11:00", "0 11 * * 0,6"),
        ("every monday at 07:30", "30 7 * * 1"),
        ("each friday at 6pm", "0 18 * * 5"),
        # Already worked, and must keep working.
        ("07:30", "30 7 * * *"),
        ("0 6 * * 1-5", "0 6 * * 1-5"),
    ],
)
def test_a_repeating_time_becomes_the_right_crontab(text, expression) -> None:
    kind, found, _next = parse_when(text, now=NOW)
    assert (kind, found) == ("cron", expression)


def test_a_repeating_job_knows_when_it_next_runs() -> None:
    # Null here is what left every cron job in the app with no next-run time.
    _kind, _expression, next_run = parse_when("every day at 18:00", now=NOW)
    assert next_run and next_run.startswith("2026-09-06T18:00")


@pytest.mark.parametrize(
    ("text", "starts"),
    [
        ("tomorrow at 20:30", "2026-09-07T20:30"),
        ("today at 23:00", "2026-09-06T23:00"),
        # Said at three in the afternoon, "at 07:30" means tomorrow morning --
        # which is what a person means, and what a scheduler that fired
        # immediately would not do.
        ("at 07:30", "2026-09-07T07:30"),
    ],
)
def test_a_one_off_lands_on_the_day_a_person_means(text, starts) -> None:
    kind, expression, _next = parse_when(text, now=NOW)
    assert kind == "once"
    assert expression.startswith(starts), expression


def test_intervals_still_work() -> None:
    assert parse_when("every 30 minutes", now=NOW)[:2] == ("interval", "30")
    assert parse_when("every 2h", now=NOW)[:2] == ("interval", "120")


def test_nonsense_says_what_would_work() -> None:
    with pytest.raises(ScheduleError, match="every day at 18:00"):
        parse_when("whenever you feel like it", now=NOW)


def test_an_impossible_clock_is_refused() -> None:
    for text in ("every day at 25:00", "every day at 10:75"):
        with pytest.raises(ScheduleError):
            parse_when(text, now=NOW)
