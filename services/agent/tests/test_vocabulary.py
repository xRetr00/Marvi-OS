"""Putting proper nouns back into a transcript.

Measured against both Parakeet models on this machine: every ordinary English
word came back right, and every proper noun came back wrong. These are the real
failures from that run, and the ones that must not be "fixed".
"""

from __future__ import annotations

import pytest

from marvi_agent.vocabulary import correct

NAMES = ["Marvi", "NeuDocs", "Shereef", "Düzce", "Kokoro", "Parakeet", "Supabase", "NeuRetro Labs"]


@pytest.mark.parametrize(
    ("heard", "expected"),
    [
        # Straight from the recogniser comparison.
        ("Tell me what you know about new docs.", "Tell me what you know about NeuDocs."),
        ("Marvey, where have you gone?", "Marvi, where have you gone?"),
        ("My name is Sheriff.", "My name is Shereef."),
        # And from the real conversation log.
        ("Tell me what do you know about new ducks?", "Tell me what do you know about NeuDocs?"),
    ],
)
def test_a_mangled_name_is_put_back(heard: str, expected: str) -> None:
    assert correct(heard, NAMES) == expected


@pytest.mark.parametrize(
    "heard",
    [
        # A wrong correction is worse than a miss: this one would read as the
        # assistant hallucinating a product into a sentence about birds.
        "The ducks are on the pond.",
        "I want to see the new features.",
        "That is more or less what I said.",
        "Can you make a note of that?",
        "It works the same way as before.",
    ],
)
def test_an_ordinary_sentence_is_left_alone(heard: str) -> None:
    assert correct(heard, NAMES) == heard


def test_a_name_already_spelled_right_is_untouched() -> None:
    assert correct("NeuDocs runs on Supabase.", NAMES) == "NeuDocs runs on Supabase."


def test_nothing_to_match_against_changes_nothing() -> None:
    """An empty graph is the normal state on a new machine."""
    assert correct("Tell me about new docs.", []) == "Tell me about new docs."


def test_an_empty_transcript_survives() -> None:
    assert correct("", NAMES) == ""


def test_punctuation_and_spacing_are_kept() -> None:
    heard = "Well, Marvey -- what about new docs?"

    assert correct(heard, NAMES) == "Well, Marvi -- what about NeuDocs?"


def test_two_names_in_one_sentence() -> None:
    assert (
        correct("Sheriff builds new docs.", NAMES) == "Shereef builds NeuDocs."
    )


def test_a_mangling_too_far_gone_is_left_alone() -> None:
    """"Morvey" for "Marvi" scores 0.545, and "new features" for "NeuRetro
    Labs" scores 0.522. Two hundredths apart, so no threshold separates them.

    The bar is set above both, which gives this one up. That is the right way
    round: a miss leaves the transcript as it was heard, and a false match
    writes a product name into a sentence about features.
    """
    assert correct("Hey Morvey, how you doing?", NAMES) == "Hey Morvey, how you doing?"
    assert correct("I want to see the new features.", NAMES) == "I want to see the new features."


def test_an_ordinary_phrase_is_not_a_project_name() -> None:
    """The turn this cost, in full.

        stt: 'need to' heard as a name; corrected to 'NeuDocs'
        turn: user said "Yeah, this very something important you NeuDocs tell me."
        turn: assistant said "I don't have anything from NeuDocs in my memory
                              right now. What would you like me to know?"

    Two words of English became a project name and Marvi answered about the
    project. `LEAVE_ALONE` cannot catch it -- that is consulted for single
    words -- and it cannot simply grow, because "new docs" is the case
    two-word spans exist for and "new" is already on the list.
    """
    names = ["NeuDocs"]
    assert correct("you need to tell me", names) == "you need to tell me"
    # And the case it must not cost: still corrected.
    assert correct("open new docs", names) == "open NeuDocs"
    assert correct("open nue docs", names) == "open NeuDocs"
