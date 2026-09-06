"""Things worth saying that could not be said yet.

Every rule that stops Marvi speaking is a rule about *now*: she is in a call,
you are out, it is three in the morning, a model is rate limited. None of them
is a reason to never say it, and until this existed they were the same thing --
the verdict downgraded, the event stayed in the journal, and that was that.

The case that made it necessary is real. The mail saying three Google mailboxes
would be permanently deleted by the end of the day arrived while nobody was
there to hear it.
"""

from __future__ import annotations

import time

import pytest

from marvi_gateway import pending, voicing
from marvi_gateway.pending import EXPIRES_AFTER, MOST_HELD, WaitingRoom


def _mail(identifier: str = "m1", says: str = "Your mailboxes are being deleted today."):
    return {
        "source": "accounts:gmail", "kind": "gmail", "trusted": False,
        "summary": "Email: Icemail #6558",
        "payload": {"id": identifier, "from": "Tiya - Icemail", "says": says},
        "at": 0.0,
    }


@pytest.fixture
def room(tmp_path) -> WaitingRoom:
    return WaitingRoom(tmp_path / "waiting.json")


def test_it_holds_what_could_not_be_said(room) -> None:
    assert room.hold(_mail(), "quiet-hours") is True
    assert [w["because"] for w in room.waiting()] == ["you were asleep"]


def test_it_does_not_hold_what_the_user_switched_off(room) -> None:
    """`initiative-paused` is a decision, not a delay.

    Holding a backlog to recite the moment somebody turns her back on is the
    exact opposite of what turning her off meant.
    """
    assert room.hold(_mail(), "initiative-paused") is False
    assert room.waiting() == []


def test_the_same_thing_is_only_held_once(room) -> None:
    # A source that re-reports the same item every poll must not fill the room
    # with copies of it.
    assert room.hold(_mail(), "nobody-present") is True
    assert room.hold(_mail(), "nobody-present") is False
    assert len(room.waiting()) == 1


def test_it_hands_back_only_what_may_be_said_now(room) -> None:
    room.hold(_mail(), "nobody-present")
    assert room.release(lambda _event: False) == [], "spoke while still blocked"
    assert len(room.waiting()) == 1

    freed = room.release(lambda _event: True)
    assert [h.explained() for h in freed] == ["you were out"]
    assert room.waiting() == [], "kept it after saying it"


def test_it_does_not_empty_the_whole_room_at_once(room) -> None:
    # Walking in the door should not be an ambush.
    for n in range(5):
        room.hold(_mail(f"m{n}"), "nobody-present")
    assert len(room.release(lambda _e: True)) == 1
    assert len(room.waiting()) == 4


def test_something_that_waited_too_long_is_dropped(room, monkeypatch) -> None:
    room.hold(_mail(), "nobody-present")
    # The real clock, captured before it is replaced: a lambda that calls
    # `time.time()` after patching `time.time` calls itself.
    later = time.time() + EXPIRES_AFTER + 60
    monkeypatch.setattr(pending.time, "time", lambda: later)
    assert room.release(lambda _e: True) == []
    assert room.waiting() == [], "recited yesterday's news"


def test_the_room_cannot_grow_forever(room) -> None:
    for n in range(MOST_HELD + 10):
        room.hold(_mail(f"m{n}"), "nobody-present")
    assert len(room.waiting()) == MOST_HELD


def test_it_survives_a_restart(tmp_path) -> None:
    """The commonest reason to be holding something is that nobody is home,
    and the second commonest is that the machine is off."""
    path = tmp_path / "waiting.json"
    WaitingRoom(path).hold(_mail(), "nobody-present")

    again = WaitingRoom(path)
    assert [w["because"] for w in again.waiting()] == ["you were out"]


def test_the_delay_is_explained_rather_than_hidden() -> None:
    """Six hours late and unexplained is alarming; explained it is care."""
    event = _mail()
    event["_waited_because"] = "you were out"
    line = voicing.spoken(event, "Shereef")
    assert line.startswith("While you were out")
    assert "mailboxes" in line


def test_nothing_is_explained_when_nothing_was_delayed() -> None:
    line = voicing.spoken(_mail(), "Shereef")
    assert not line.startswith("While")
