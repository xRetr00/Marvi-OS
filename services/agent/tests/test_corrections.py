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
