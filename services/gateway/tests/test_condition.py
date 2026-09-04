"""The Gateway saying what it is doing, instead of going quiet.

A health poll either got an answer or did not, and "did not" became `Gateway
unavailable` -- a sentence equally true of a crash, a restart, a busy loop and
a model loading. The one that actually happened was the least alarming of the
four: the embedding model's first encode takes about ten seconds, the loop
could not answer anything during it, and the status bar reported it as gone.
"""

from __future__ import annotations

import time

import pytest

from marvi_gateway import condition
from marvi_gateway.condition import Strain


@pytest.fixture(autouse=True)
def _clean():
    condition.forget()
    yield
    condition.forget()


def test_it_says_what_it_is_in_the_middle_of() -> None:
    assert condition.now() == ""
    with condition.doing("loading the memory model"):
        assert condition.now() == "loading the memory model"
    assert condition.now() == ""


def test_the_innermost_answer_is_the_useful_one() -> None:
    # "loading the memory model" tells somebody something; "answering a
    # recall" tells them nothing they did not already know.
    with condition.doing("answering a recall"):
        with condition.doing("loading the memory model"):
            assert condition.now() == "loading the memory model"
        assert condition.now() == "answering a recall"


def test_being_busy_is_not_the_same_as_dragging() -> None:
    """A status line should fill in exactly when a person starts wondering."""
    with condition.doing("thinking"):
        assert condition.dragging() == "", "a fast call should say nothing"
        assert condition.dragging(threshold=0.0) == "thinking"


def test_something_slow_is_remembered_for_afterwards() -> None:
    with condition.doing("loading the memory model"):
        time.sleep(condition.WORTH_MENTIONING + 0.05)

    strain = condition.recent()
    assert strain is not None
    assert "loading the memory model" in strain.sentence()


def test_something_quick_is_not_worth_mentioning() -> None:
    # Otherwise every request leaves a note and the interesting one is buried.
    with condition.doing("answering"):
        pass
    assert condition.recent() is None


def test_a_failure_is_remembered_however_fast_it_was() -> None:
    with pytest.raises(RuntimeError):
        with condition.doing("reaching the room"):
            raise RuntimeError("connection refused")

    strain = condition.recent()
    assert strain is not None
    assert "reaching the room failed" in strain.sentence()
    assert "connection refused" in strain.sentence()


def test_the_exception_still_reaches_the_caller() -> None:
    # Naming what went wrong must never swallow it.
    with pytest.raises(ValueError, match="nope"):
        with condition.doing("something"):
            raise ValueError("nope")


def test_it_stops_apologising_for_old_news() -> None:
    with condition.doing("loading the memory model"):
        time.sleep(condition.WORTH_MENTIONING + 0.05)

    assert condition.recent() is not None
    stale = time.time() + condition.REMEMBERED_FOR + 1
    assert condition.recent(now_at=stale) is None


def test_the_sentence_is_speakable() -> None:
    """The announcer reads these aloud, so "took 1 seconds" is not acceptable."""
    assert Strain("loading the memory model", 1.0, 0).sentence().endswith("1 second")
    assert Strain("loading the memory model", 10.7, 0).sentence().endswith("11 seconds")


def test_nested_work_unwinds_in_any_order() -> None:
    # Two overlapping operations must not leave a phantom "still doing" behind
    # when the outer one finishes first.
    outer = condition.doing("outer")
    inner = condition.doing("inner")
    outer.__enter__()
    inner.__enter__()
    outer.__exit__(None, None, None)
    assert condition.now() == "inner"
    inner.__exit__(None, None, None)
    assert condition.now() == ""
