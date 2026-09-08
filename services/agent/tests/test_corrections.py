"""Keeping a correction in front of her. See `corrections`."""

from __future__ import annotations

from marvi_agent.corrections import Corrections


def test_a_correction_names_her_own_words() -> None:
    """The half that does the work, and the half the first version missed.

    Measured at 24 samples a variant, same conversation, same model:

        11/24  45%   nothing
        13/24  54%   the user's complaint quoted, and nothing else
         2/24   8%   the complaint quoted *and her own last reply named*

    Quoting the complaint alone is no better than doing nothing: it says
    somebody is unhappy without saying which words to drop.
    """
    notes = Corrections()

    assert notes.heard(
        "Why do you saying good night when I'm telling you it's morning?",
        "Goodnight, Shereef. Sleep well.",
    )
    said = notes.block()

    assert "Goodnight, Shereef. Sleep well." in said, "her own sentence must be named"
    assert "do not say it again" in said


def test_an_ordinary_turn_is_not_a_correction() -> None:
    """A note in front of every turn is the bloat this exists to avoid."""
    notes = Corrections()

    assert not notes.heard("Just going to sleep.", "Good morning.")
    assert not notes.heard("okay", "")
    assert not notes.heard("what is the weather", "")
    assert notes.block() == ""


def test_it_is_held_for_a_few_turns_and_then_let_go() -> None:
    """The failure repeated across the two turns after the correction, and a
    correction still being recited on the tenth turn reads as an assistant
    that cannot let something go."""
    from marvi_agent.corrections import HELD_FOR_TURNS

    notes = Corrections()
    notes.heard("you keep saying that", "Goodnight, Shereef.")

    seen = [notes.block() for _ in range(HELD_FOR_TURNS)]
    assert all(seen), "it must survive the turns that follow the correction"
    assert notes.block() == "", "and stop after that"


def test_it_survives_not_knowing_what_she_said() -> None:
    """`_last_thing_she_said` returns empty on the first turn of a session."""
    notes = Corrections()

    assert notes.heard("stop saying that", "")
    said = notes.block()

    assert said, "a correction with no prior reply is still worth carrying"
    assert "do not repeat" in said


def test_saying_the_same_thing_twice_is_noticed_without_being_told() -> None:
    """The signal that needs nothing from the user.

    In a real session she said "Goodnight, Shereef." three times and "Good
    morning, Shereef. I'm glad you're awake." verbatim twice, while the user
    objected in four different phrasings -- none of which the first version of
    `CORRECTING` matched. Repetition is visible without parsing an objection.
    """
    notes = Corrections()

    assert notes.repeating("Goodnight, Shereef.") == ""
    # The same reply, spelled the other way, is the same reply.
    said = notes.repeating("Good night, Shereef")
    assert "twice in a row" in said
    assert "Do not say it a third time" in said

    # A different answer clears it.
    assert notes.repeating("Good morning, Shereef.") == ""


def test_the_real_corrections_from_a_live_session_are_caught() -> None:
    """The first version fired once in five real chances.

        "It's not night, it's morning."               missed
        "No, I am going to sleep and it's morning."   missed
        "But it's morning."                           missed
        "No, it's morning."                           missed
        "No, don't say good night when it's morning." caught

    It had been written from a single transcript that happened to phrase every
    objection as "why do you" or "you don't understand".
    """
    from marvi_agent.corrections import CORRECTING

    for said in (
        "It's not night, it's morning.",
        "No, I am going to sleep and it's morning.",
        "But it's morning.",
        "No, it's morning.",
        "No it is morning",
        "No, don't say good night when it's good morning.",
    ):
        assert CORRECTING.search(said), said

    # And ordinary turns from the same session stay ordinary. "no problem" is
    # a courtesy, not a correction -- the comma is what separates them.
    for said in (
        "I am going to sleep.",
        "Yeah, I'm just going to sleep right now.",
        "Hey Marvey, how you doing?",
        "no problem, thanks",
        "turn the light on",
    ):
        assert not CORRECTING.search(said), said
