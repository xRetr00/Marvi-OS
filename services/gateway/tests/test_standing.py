"""The paragraph that stands in front of every turn. See `standing`."""

from __future__ import annotations


def test_a_brief_about_somebody_else_is_refused() -> None:
    """It named a person who does not exist, for half a day.

        Brady Vine is building Marvi, a voice-first local AI assistant,
        under the codename Marvey.

    The notes say Shereef -- one memory's entire body is "The user's name is
    Shereef" -- and the model wrote a name anyway. It went into the system
    prompt of every turn, asserted as fact, while another block in the same
    prompt said Shereef. The previous brief, stale but about the right person,
    is better than a current one about a stranger.
    """
    from marvi_gateway.standing import settled

    invented = (
        "Brady Vine is building Marvi, a voice-first local AI assistant. "
        "He has a friend named Kenny."
    )
    assert settled(invented, "Shereef") == ""

    # A friend named in a later sentence is not the subject and is kept.
    right = "Shereef is building Marvi. He has a friend named Kenny."
    assert "Kenny" in settled(right, "Shereef")


def test_this_mornings_state_is_not_a_standing_fact() -> None:
    """She recited it back as current four hours after it was fixed.

        user:  Just some bugs you having.
        marvi: I know I have some bugs. The Agent voice engine keeps
               restarting and the room sidecar process is down.
        user:  Yeah, but I did fix those issues.

    The prompt that builds the brief asks for nothing temporary. Asking is not
    enough when the cost of a slip is a standing falsehood.
    """
    from marvi_gateway.standing import settled

    brief = (
        "Shereef is building Marvi. "
        "The Sidecar process is currently down. "
        "The Agent voice engine keeps restarting. "
        "Gmail needs re-authentication. "
        "The room light is on at 70 percent. "
        "He prefers short answers."
    )
    kept = settled(brief, "Shereef")

    assert "currently down" not in kept
    assert "keeps restarting" not in kept
    assert "re-authentication" not in kept
    assert "70 percent" not in kept
    assert "prefers short answers" in kept


def test_the_brief_is_cut_at_a_sentence() -> None:
    """The live one ended "Shereef is lik" -- a hard slice at MAX_CHARS."""
    from marvi_gateway.standing import MAX_CHARS, settled

    long = " ".join(f"Shereef does durable thing number {i}." for i in range(80))
    kept = settled(long, "Shereef")

    assert len(kept) <= MAX_CHARS
    assert kept.endswith("."), "a brief must not stop mid-word"


def test_the_users_name_is_readable() -> None:
    """`identity.user_path` is a property on `IdentityFiles`, and four call
    sites called it as a module function inside `contextlib.suppress` -- so
    every one of them silently returned no name at all."""
    from marvi_gateway.identity import IdentityFiles

    assert not callable(IdentityFiles().user_path), "it is a Path, not a function"
