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


def test_the_context_blocks_are_ordered_static_first() -> None:
    """The order was whatever the dict happened to be, and it cost twice.

    These blocks are appended after the agent's instructions, so the last one
    sits closest to the conversation. That slot went to the skills catalogue --
    1,788 characters of names that do not change between turns -- while "what
    is happening right now" sat in the middle, where long-context models
    retrieve worst.

    And a cache hit is a matching prefix, so a volatile block early in the list
    invalidates every static block after it: the room light changing re-sent
    two kilobytes of unchanged skills and soul.
    """
    from marvi_gateway.app import ordered_context_blocks

    # Deliberately given in the old, accidental order.
    given = {
        "situation": "where you live",
        "soul": "# Marvi",
        "user": "about the person",
        "standing": "who you are talking to",
        "world": "what is happening right now",
        "accounts": "accounts connected",
        "skills": "# Skills you can use",
    }
    out = ordered_context_blocks(given)

    assert out[0] == "# Skills you can use", "the most static block goes first"
    assert out[-1] == "what is happening right now", "the freshest goes nearest the turn"
    assert out.index("# Skills you can use") < out.index("what is happening right now")

    # Empty blocks are dropped rather than sent as blank lines.
    assert ordered_context_blocks({"world": "", "soul": "# Marvi"}) == ["# Marvi"]

    # A block nobody ranked still travels, after the ranked ones.
    out = ordered_context_blocks({"soul": "# Marvi", "brand_new": "something else"})
    assert out == ["# Marvi", "something else"]
