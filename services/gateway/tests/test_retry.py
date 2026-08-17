"""Retry, and the things it must refuse to do.

The interesting tests here are the negative ones. Retrying a read is easy;
*not* retrying a send is the property that keeps someone from receiving the
same email three times.
"""

from __future__ import annotations

import logging
import random

import pytest

from marvi_gateway import breadcrumb
from marvi_gateway.retry import (
    EXTERNAL_WRITE,
    READ_ONLY,
    Policy,
    RetriesExhaustedError,
    is_repeatable,
    once,
    policy_for,
    retry,
)


def flaky(failures: int, error: type[Exception] = ConnectionError):
    """Fails a set number of times, then succeeds."""
    state = {"calls": 0}

    def operation() -> str:
        state["calls"] += 1
        if state["calls"] <= failures:
            raise error(f"attempt {state['calls']}")
        return "ok"

    operation.calls = state  # type: ignore[attr-defined]
    return operation


def no_sleep(_seconds: float) -> None:
    """Tests must not actually wait out a backoff."""


# -- retrying ------------------------------------------------------------------


def test_a_transient_failure_is_ridden_out() -> None:
    operation = flaky(2)

    assert retry(operation, "read", sleep=no_sleep) == "ok"
    assert operation.calls["calls"] == 3


def test_a_permanent_failure_gives_up_and_says_so() -> None:
    operation = flaky(99)

    # A retry that ends in silence is worse than the original error: the caller
    # waited longer and still has nothing.
    with pytest.raises(RetriesExhaustedError) as raised:
        retry(operation, "read", sleep=no_sleep)

    assert raised.value.attempts == READ_ONLY.attempts
    assert isinstance(raised.value.cause, ConnectionError)


def test_success_first_time_costs_nothing() -> None:
    waits: list[float] = []
    retry(lambda: "fine", "read", sleep=waits.append)

    assert waits == []


def test_an_error_that_will_not_improve_is_not_retried() -> None:
    operation = flaky(99, error=PermissionError)

    with pytest.raises(PermissionError):
        retry(operation, "read", give_up_on=(PermissionError,), sleep=no_sleep)

    # A rejected credential does not become valid on the third attempt.
    assert operation.calls["calls"] == 1


def test_giving_up_wins_over_retrying_when_both_match() -> None:
    operation = flaky(99, error=PermissionError)

    with pytest.raises(PermissionError):
        retry(
            operation, "read",
            retry_on=(Exception,), give_up_on=(PermissionError,), sleep=no_sleep,
        )
    assert operation.calls["calls"] == 1


# -- the backoff ---------------------------------------------------------------


def test_the_wait_grows_and_is_capped() -> None:
    policy = Policy(base_seconds=1.0, max_seconds=4.0)
    fixed = random.Random(0)

    # Full jitter draws from [0, ceiling], so assert the ceiling rather than
    # the value.
    assert all(policy.wait_for(1, fixed) <= 1.0 for _ in range(20))
    assert all(policy.wait_for(3, fixed) <= 4.0 for _ in range(20))
    assert all(policy.wait_for(9, fixed) <= 4.0 for _ in range(20))


def test_the_wait_is_jittered_not_fixed() -> None:
    policy = Policy(base_seconds=4.0)
    draws = {policy.wait_for(3) for _ in range(30)}

    # Subsystems retrying in lockstep reconverge on the failing thing, which is
    # an outage of its own making.
    assert len(draws) > 1


def test_the_total_time_budget_stops_it_early() -> None:
    clock = {"now": 0.0}
    policy = Policy(attempts=99, base_seconds=1.0, budget_seconds=3.0)

    def tick(seconds: float) -> None:
        clock["now"] += seconds

    operation = flaky(99)
    with pytest.raises(RetriesExhaustedError):
        retry(
            operation, "read", policy=policy,
            sleep=tick, now=lambda: clock["now"], rng=random.Random(1),
        )

    # Four attempts with a long backoff can still leave someone on a spinner.
    assert operation.calls["calls"] < 99
    assert clock["now"] <= policy.budget_seconds + policy.max_seconds


# -- what must never be retried -------------------------------------------------


def test_an_external_write_is_attempted_exactly_once() -> None:
    operation = flaky(99)

    with pytest.raises(RetriesExhaustedError):
        retry(operation, "send email", policy=EXTERNAL_WRITE, sleep=no_sleep)

    # Re-reading a room state twice costs nothing. Re-sending an email twice is
    # a second email.
    assert operation.calls["calls"] == 1


def test_once_is_the_same_thing_said_at_the_call_site() -> None:
    operation = flaky(99)

    with pytest.raises(RetriesExhaustedError):
        once(operation, "send email")
    assert operation.calls["calls"] == 1


def test_a_contradictory_policy_resolves_the_cautious_way() -> None:
    operation = flaky(99)
    contradiction = Policy(attempts=5, repeatable=False)

    with pytest.raises(RetriesExhaustedError):
        retry(operation, "send", policy=contradiction, sleep=no_sleep)

    assert operation.calls["calls"] == 1


class Tool:
    def __init__(self, external: bool) -> None:
        self.external = external


def test_a_tool_marked_external_is_not_repeatable() -> None:
    assert is_repeatable(Tool(external=True)) is False
    assert is_repeatable(Tool(external=False)) is True
    assert policy_for(Tool(external=True)).attempts == 1
    assert policy_for(Tool(external=False)) is READ_ONLY


def test_an_unrecognised_object_is_treated_as_unsafe() -> None:
    # Guessing wrong in the other direction sends a second email.
    assert is_repeatable(object()) is False


# -- the crash breadcrumb --------------------------------------------------------


@pytest.fixture
def crumbs(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVI_LOG_DIR", str(tmp_path / "logs"))
    breadcrumb.clear()
    yield tmp_path
    breadcrumb.clear()


def test_a_crash_leaves_a_note_the_next_launch_can_read(crumbs) -> None:
    breadcrumb.record("RuntimeError: exploded", "the traceback")

    pending = breadcrumb.pending()
    assert pending[0]["reason"] == "RuntimeError: exploded"
    assert pending[0]["detail"] == "the traceback"


def test_the_note_is_cleared_once_reported(crumbs) -> None:
    breadcrumb.record("RuntimeError: exploded")
    breadcrumb.report_and_clear()

    # Otherwise the same crash is announced on every launch forever.
    assert breadcrumb.pending() == []


def test_a_pattern_of_crashes_is_kept_not_just_the_last(crumbs) -> None:
    for n in range(8):
        breadcrumb.record(f"crash {n}")

    kept = breadcrumb.pending()
    # One crash is an incident; several is the more useful thing to show.
    assert len(kept) == breadcrumb.MAX_CRUMBS
    assert kept[-1]["reason"] == "crash 7"


def test_a_secret_in_a_crash_note_is_scrubbed(crumbs, monkeypatch) -> None:
    from marvi_gateway import logs

    monkeypatch.setenv("OPENAI_API_KEY", "sk-crashnote-secret-123")
    logs.redactor().refresh()
    breadcrumb.record("failed", "traceback with sk-crashnote-secret-123 in it")

    # This file ends up in Copy diagnostics like everything else.
    assert "sk-crashnote-secret-123" not in str(breadcrumb.pending())


def test_recording_never_raises_even_when_it_cannot_write(crumbs, monkeypatch) -> None:
    monkeypatch.setattr(
        "marvi_gateway.breadcrumb.crumb_path",
        lambda: crumbs / "no" / "such" / "dir" / "x" / "\0bad.json",
    )

    # The process is already falling over; the breadcrumb must not make it worse.
    assert breadcrumb.record("something") is None


def test_a_clean_interrupt_leaves_no_crash_note(crumbs) -> None:
    import sys

    breadcrumb.install("gateway")
    original = sys.__excepthook__
    sys.__excepthook__ = lambda *_: None  # type: ignore[assignment]
    try:
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    finally:
        sys.__excepthook__ = original  # type: ignore[assignment]

    # Ctrl-C is a user action, not a crash.
    assert breadcrumb.pending() == []


def test_an_optional_dependency_giving_up_is_not_an_error(caplog) -> None:
    """The room sidecar is a program the user may never start.

    Logging that at ERROR once per poll filled errors.log with the one thing
    that was working as designed, and buried the ones that were not.
    """
    policy = Policy(attempts=2, base_seconds=0, budget_seconds=10, optional=True)

    def always_fails() -> None:
        raise ConnectionRefusedError("sidecar is not reachable")

    with caplog.at_level(logging.INFO, logger="marvi.retry"):
        with pytest.raises(RetriesExhaustedError):
            retry(always_fails, "room.get_state", policy=policy, sleep=lambda _: None)

    gave_up = [r for r in caplog.records if "gave up" in r.getMessage()]
    assert gave_up, "giving up is still reported — quietly, not silently"
    assert all(r.levelno < logging.WARNING for r in gave_up)


def test_a_required_dependency_giving_up_is_still_an_error(caplog) -> None:
    policy = Policy(attempts=2, base_seconds=0, budget_seconds=10)

    def always_fails() -> None:
        raise ConnectionRefusedError("gateway is down")

    with caplog.at_level(logging.INFO, logger="marvi.retry"):
        with pytest.raises(RetriesExhaustedError):
            retry(always_fails, "provider.call", policy=policy, sleep=lambda _: None)

    assert any(r.levelno == logging.ERROR for r in caplog.records)
