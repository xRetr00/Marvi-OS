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
        # `id` because a held event goes back through the mind exactly as a
        # fresh one does, and that path marks it processed by id.
        "id": 1,
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


def test_something_unread_waits_for_a_model_not_a_moment(room) -> None:
    """"The rate limit has cleared, say it."

    `gatekeeping` fails open when no model will answer, so the item is kept and
    never summarised -- and `policy` will not announce mail nobody read. That
    is not a reason to lose it: it is the most temporary blocker of all. It
    waits for a working model rather than for a better moment.
    """
    unread = _mail(says="")
    unread["payload"].pop("says")
    unread["payload"]["body"] = "Your mailboxes will be permanently deleted today."

    assert room.hold(unread, "unread") is True
    # The wording is the user-facing half and it changed: "I could not read it
    # at the time" reads as an excuse for a failure. It is not one -- the item
    # is held precisely so nothing is lost -- so it says what happened instead.
    assert [w["because"] for w in room.waiting()] == ["I had not read it yet"]


def test_the_policy_calls_unread_mail_unread() -> None:
    """So the waiting room can tell it apart from an ordinary allow."""
    from datetime import UTC, datetime

    from marvi_gateway.policy import InitiativeSettings, WorldState, evaluate

    world = WorldState(now=datetime(2026, 9, 6, 12, 0, tzinfo=UTC), present=True)
    unread = _mail()
    unread["payload"].pop("says")

    verdict = evaluate(unread, world, InitiativeSettings(), wanted="speak")
    assert verdict.rule == "unread"
    assert verdict.surface == "island", "announced something nobody had read"

    # And the same mail, once something has read it.
    verdict = evaluate(_mail(), world, InitiativeSettings(), wanted="speak")
    assert verdict.surface == "speak"


def test_the_mind_actually_holds_what_it_cannot_say(room) -> None:
    """Exercises `Mind.tick` itself, not just the room.

    Written because it did not exist: the holding call read `verdict.reason`
    and the field is `verdict.rule`, so the first thing Marvi ever tried to
    hold would have raised. Every test passed, because nothing drove the mind
    with a waiting room attached.
    """
    from datetime import UTC, datetime

    from marvi_gateway.mind import Mind

    said = _mail()

    class _Journal:
        """Only what `Mind.tick` actually reaches for."""

        def pending(self, limit=20):
            return [dict(said, id=1)]

        def tokens_since(self, _when):
            return 0

        def last_surfaced(self, _source, _kind):
            return None

        def seen_recently(self, *_args, **_kwargs):
            return 0

        def record_decision(self, *_args, **_kwargs):
            return 1

        def mark_processed(self, *_args, **_kwargs):
            return None

    mind = Mind(_Journal())
    mind.waiting = room

    # Mid-call: the foreground owns the voice, so this cannot be said now.
    mind.tick(now=datetime(2026, 9, 6, 12, 0, tzinfo=UTC), conversation_active=True)

    assert [w["because"] for w in room.waiting()] == ["we were talking"], (
        "the mind dropped something it should have held"
    )


def test_a_cooldown_is_waited_out_not_walked_into(room) -> None:
    """The 300-second refusal, handled instead of hit.

        provider openrouter cooling down 300s: rate limited or window exhausted

    The cooldown was always tracked and nothing consulted it, so anything
    wanting a model met the same refusal every couple of minutes -- and the
    thing waiting was the summary of a mail saying three mailboxes would be
    deleted that day.
    """
    from datetime import UTC, datetime

    from marvi_gateway.mind import Mind

    unread = _mail(says="")
    unread["payload"].pop("says")
    unread["payload"]["body"] = "Your mailboxes will be deleted today."
    room.hold(unread, "unread")

    tried: list[str] = []
    mind = Mind(_journal_of())
    mind.waiting = room
    mind.read_late = lambda subject, _body: tried.append(subject) or "read it"

    # Cooling down: nothing is attempted and nothing is lost.
    mind.models_resting = lambda: 240.0
    mind.tick(now=datetime(2026, 9, 6, 12, 0, tzinfo=UTC))
    assert tried == [], "asked a model that had said it was cooling down"
    assert len(room.waiting()) == 1, "dropped it instead of holding it"

    # Cleared: read now, and released.
    mind.models_resting = lambda: 0.0
    mind.tick(now=datetime(2026, 9, 6, 12, 5, tzinfo=UTC))
    assert tried, "never went back for it once a model was free"
    assert room.waiting() == []


def _journal_of(events=None):
    class _Journal:
        def pending(self, limit=20):
            return list(events or [])

        def tokens_since(self, _when):
            return 0

        def last_surfaced(self, _source, _kind):
            return None

        def seen_recently(self, *_args, **_kwargs):
            return 0

        def record_decision(self, *_args, **_kwargs):
            return 1

        def mark_processed(self, *_args, **_kwargs):
            return None

    return _Journal()
