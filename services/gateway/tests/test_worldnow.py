"""What Marvi's own senses report, in one block on every turn.

The Mind read the room, the desktop and the journal to decide whether to
interrupt. Marvi -- the one actually talking -- read none of it, and the pieces
reached her by separate paths when they reached her at all, so the same
question got a different answer depending on which tool the model thought of.
"""

from __future__ import annotations

from marvi_gateway.worldnow import MAX_CHARS, describe

ROOM = {
    "light": {"on": True, "brightness": 70},
    "modes": {"active_mode": "focus"},
    "presence": {"detected": True},
}


def test_nothing_known_says_nothing() -> None:
    # A machine with no room plugin and no ActivityWatch has no world context,
    # and a block announcing that would cost tokens to invite speculation.
    assert describe(None, None) == ""
    assert describe({}, {}) == ""


def test_it_names_the_room_the_desktop_and_the_day() -> None:
    block = describe(ROOM, {"summary": "in Code, browsing github.com"},
                     recent_apps=["Code", "chrome"])
    assert "light is on at 70%" in block
    assert "focus mode" in block
    assert "someone is in the room" in block
    assert "in Code, browsing github.com" in block
    assert "today they have used Code, chrome" in block


def test_an_empty_room_is_said_plainly() -> None:
    # Lower-cased for the comparison: the block capitalises its first word,
    # so "the light is off" arrives as "The light is off".
    block = describe({"presence": {"detected": False}, "light": {"on": False}}, None).lower()
    assert "the room is empty" in block
    assert "the light is off" in block


def test_a_blind_sensor_is_not_reported_as_a_fact() -> None:
    """"no activity data" is the adapter saying it cannot see.

    Passing that through invites her to announce her own instrumentation.
    """
    assert describe(None, {"summary": "no activity data"}) == ""


def test_each_part_is_optional() -> None:
    assert "light" in describe(ROOM, None).lower()
    assert "they are" in describe(None, {"summary": "at the machine"}).lower()
    assert "today they have used" in describe(None, None, recent_apps=["Code"]).lower()


def test_the_block_stays_short() -> None:
    """Paid on every turn of every conversation."""
    block = describe(ROOM, {"summary": "x" * 500}, recent_apps=["app"] * 40)
    body = block.splitlines()[2]
    assert len(body) <= MAX_CHARS + 1


def test_it_tells_her_not_to_recite_it() -> None:
    # The failure this shape guards against: reading the context aloud instead
    # of using it.
    assert "never recite it" in describe(ROOM, None)
