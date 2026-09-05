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
    with pytest.raises(RuntimeError), condition.doing("reaching the room"):
        raise RuntimeError("connection refused")

    strain = condition.recent()
    assert strain is not None
    assert "reaching the room failed" in strain.sentence()
    assert "connection refused" in strain.sentence()


def test_the_exception_still_reaches_the_caller() -> None:
    # Naming what went wrong must never swallow it.
    with pytest.raises(ValueError, match="nope"), condition.doing("something"):
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


def test_a_caller_with_its_own_threshold_is_believed() -> None:
    """A blocked event loop is notable however short it measures.

    `watchdog` measures a block as overshoot from a one-second heartbeat, so a
    stall that began mid-interval arrives here looking smaller than it was --
    a real 1.4s block reports as 0.6s. Its own threshold has already decided;
    the general duration gate must not throw the finding away.
    """
    condition.note("busy with something on the main loop", 0.6, regardless=True)
    strain = condition.recent()
    assert strain is not None and "main loop" in strain.sentence()


def test_the_general_gate_still_filters_ordinary_noise() -> None:
    # Without it every request leaves a note and the interesting one is buried.
    condition.note("answering /runtime", 0.01)
    assert condition.recent() is None


def test_a_line_is_handed_over_exactly_once() -> None:
    """Otherwise Marvi mentions the same pause at the start of every turn.

    The aside is collected at every turn boundary, so "is there anything to
    say" is asked constantly. Saying it once is the whole difference between
    an assistant explaining itself and one that will not let it go.
    """
    condition.note("loading the memory model", 10.7)

    first = condition.worth_saying("Shereef")
    assert "memory model" in first
    assert condition.worth_saying("Shereef") == ""
    assert condition.worth_saying("Shereef") == ""


def test_something_new_is_worth_saying_once_the_quiet_window_passes(monkeypatch) -> None:
    """Superseded by `NOT_AGAIN_WITHIN`, and deliberately.

    This used to assert that a second strain was immediately worth saying.
    That is how a rough patch becomes a monologue, so a new strain now waits
    out the quiet window like anything else -- but it must not be silenced
    forever, which is what this pins.
    """
    condition.note("loading the memory model", 10.7)
    assert condition.worth_saying("Shereef")

    monkeypatch.setattr(condition, "NOT_AGAIN_WITHIN", 0.0)
    condition.note("reaching the room", 11.0)
    assert "reaching the room" in condition.worth_saying("Shereef")


def test_a_failure_does_not_get_the_words_for_slowness() -> None:
    # `condition` records what she was *doing* -- a verb phrase -- and the
    # component wording produced "something wrong with my reaching the room".
    condition.note("reaching the room", 0.1, failed="connection refused")
    line = condition.worth_saying("Shereef")

    assert "wrong with my reaching" not in line
    assert "reaching the room" in line
    assert "why I was slow" not in line


def test_nothing_to_say_is_the_normal_answer() -> None:
    assert condition.worth_saying("Shereef") == ""


def test_an_ordinary_pause_is_not_worth_interrupting_for() -> None:
    """The regression that made Marvi apologise on every single turn.

    A voice call blocks the loop constantly and briefly -- that is what a voice
    call is. Recording a second of lag is right; saying it out loud produced

        MARVI  I was answering /memory/recall just then, which is why I was slow.
        MARVI  Hey, that took a moment because I was busy with something on the
               main loop.

    turn after turn, for pauses nobody had noticed until she mentioned them.
    """
    for seconds in (0.4, 1.2, 3.0):
        condition.forget()
        condition.note("busy with something on the main loop", seconds, regardless=True)
        assert condition.worth_saying("Shereef") == "", f"{seconds}s should stay quiet"


def test_a_pause_long_enough_to_notice_is_explained() -> None:
    # The 12.3-second block that was really there. By then the person has
    # already wondered, and explaining is a kindness rather than an intrusion.
    condition.note("busy with something on the main loop", 12.3, regardless=True)
    assert condition.worth_saying("Shereef")


def test_a_failure_is_worth_saying_however_quick() -> None:
    # Being slow and being broken are different news.
    condition.note("reaching the room", 0.1, failed="connection refused")
    assert condition.worth_saying("Shereef")


def test_she_does_not_make_a_rough_patch_everybody_is_problem() -> None:
    condition.note("loading the memory model", 12.0)
    assert condition.worth_saying("Shereef")

    # A second bad pause soon after is real, and saying so again is not.
    condition.note("answering /memory/recall", 11.0)
    assert condition.worth_saying("Shereef") == ""
