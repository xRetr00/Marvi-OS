"""Ending a call that nobody is in.

Two sessions in one real day ran 305 and 137 minutes with the microphone open,
answering whatever was said in an empty room. Nothing was broken -- the wake
word runs in its own host and only launches the app, and every rule about when
to speak worked as written. The session simply had no end.
"""

from __future__ import annotations

import asyncio

import pytest

from marvi_agent import alone
from marvi_agent.alone import QUIET_AND_ALONE, QUIET_AND_PRESENT, Alone


def _quiet_for(seconds: float, **kwargs) -> Alone:
    watcher = Alone(**kwargs)
    watcher._last -= seconds
    return watcher


def test_a_fresh_call_is_never_ended() -> None:
    assert Alone().should_leave(there=True) == ""
    assert Alone().should_leave(there=False) == ""


def test_somebody_thinking_is_given_room() -> None:
    """A person who is present and quiet has not finished talking to you.

    Interrupting a pause is rude; the whole point of two thresholds is that
    this silence and an empty room are not the same silence.
    """
    watcher = _quiet_for(QUIET_AND_PRESENT - 30)
    assert watcher.should_leave(there=True) == ""


def test_an_empty_room_is_left_quickly() -> None:
    watcher = _quiet_for(QUIET_AND_ALONE + 5)
    assert watcher.should_leave(there=False) == "the room is empty"


def test_a_long_silence_ends_it_even_with_somebody_there() -> None:
    watcher = _quiet_for(QUIET_AND_PRESENT + 5)
    assert watcher.should_leave(there=True) == "nobody has said anything"


def test_unknown_presence_is_treated_as_present() -> None:
    """Ending a call because a sensor went quiet is the same failure as never
    ending one, pointed the other way."""
    watcher = _quiet_for(QUIET_AND_ALONE + 5)
    assert watcher.should_leave(there=None) == "", "left on a sensor blinking off"
    assert _quiet_for(QUIET_AND_PRESENT + 5).should_leave(there=None) == "nobody has said anything"


def test_anybody_speaking_keeps_it_alive() -> None:
    watcher = _quiet_for(QUIET_AND_PRESENT + 60)
    watcher.heard()
    assert watcher.should_leave(there=True) == ""

    watcher = _quiet_for(QUIET_AND_PRESENT + 60)
    # A long answer she is still delivering is not an idle call.
    watcher.spoke()
    assert watcher.should_leave(there=True) == ""


def test_a_broken_presence_check_does_not_end_the_call() -> None:
    def explode() -> bool:
        raise OSError("the room is unreachable")

    watcher = _quiet_for(QUIET_AND_ALONE + 5, present=explode)
    assert watcher._somebody_there() is None
    assert watcher.should_leave(watcher._somebody_there()) == ""


def test_she_says_something_before_leaving_a_person() -> None:
    assert alone.farewell_for("nobody has said anything")
    # And nothing to an empty room: there is no one to hear it.
    assert alone.farewell_for("the room is empty") == ""


def test_it_leaves_once_and_only_once() -> None:
    watcher = _quiet_for(QUIET_AND_PRESENT + 60, present=lambda: True)
    left: list[str] = []

    async def drive() -> None:
        async def leave(why: str) -> None:
            left.append(why)

        watcher_task = asyncio.create_task(watcher.watch(leave))
        # Several look intervals, so a second firing would show up. Generous
        # because the presence check hops to a thread.
        for _ in range(60):
            await asyncio.sleep(0.01)
            if left and watcher_task.done():
                break
        watcher_task.cancel()

    original = alone.LOOK_EVERY
    alone.LOOK_EVERY = 0.01
    try:
        asyncio.run(drive())
    finally:
        alone.LOOK_EVERY = original

    assert left == ["nobody has said anything"], f"left {len(left)} times"


@pytest.mark.parametrize("seconds", [0, 30, QUIET_AND_ALONE - 1])
def test_the_short_patience_is_never_undercut(seconds) -> None:
    # Below the shorter threshold nothing ends, whatever presence says --
    # otherwise a momentary sensor drop cuts somebody off mid-thought.
    assert _quiet_for(seconds).should_leave(there=False) == ""
