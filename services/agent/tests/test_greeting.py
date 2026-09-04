"""The first thing Marvi says, and the times she should say nothing.

A call opened on silence -- both sides waiting for the other to start. What
makes a greeting warm rather than irritating is entirely in knowing when to
skip it.
"""

from __future__ import annotations

import pytest

from marvi_agent import greeting


@pytest.mark.parametrize(
    ("hour", "expected"),
    [(9, "morning"), (15, "afternoon"), (20, "evening")],
)
def test_she_knows_what_time_it_is(hour: int, expected: str) -> None:
    assert expected in greeting.opening("Shereef", hour=hour, seed=0).lower()


def test_one_in_the_morning_is_not_greeted_as_a_working_day() -> None:
    """"Good night" as a hello is the tell that nothing is really paying attention."""
    lines = {greeting.opening("Shereef", hour=1, seed=n) for n in range(6)}
    assert lines
    for line in lines:
        assert "good night" not in line.lower()
        assert any(word in line for word in ("Still up", "Late one", "I am here"))


def test_a_rejoin_is_a_conversation_continuing() -> None:
    # Hang up, remember something, come back. Being welcomed again is the
    # assistant not noticing it just spoke to you.
    line = greeting.opening("Shereef", hour=15, since_last_call=20.0, seed=0)
    assert "Good afternoon" not in line
    assert any(word in line for word in ("Still here", "Back with you", "Go on"))


def test_coming_back_much_later_is_an_arrival_again() -> None:
    line = greeting.opening("Shereef", hour=15, since_last_call=3_600.0, seed=0)
    assert "afternoon" in line.lower()


def test_being_called_by_name_gets_out_of_the_way() -> None:
    """Saying "Marvi" means the request is already coming."""
    for seed in range(6):
        line = greeting.opening("Shereef", hour=9, by_wake_word=True, seed=seed)
        assert len(line) < 30, f"too long to say over somebody: {line!r}"
        assert "morning" not in line.lower()


def test_no_name_still_reads_as_a_sentence() -> None:
    for seed in range(9):
        for hour in (1, 9, 15, 20):
            line = greeting.opening("", hour=hour, seed=seed)
            assert line and "None" not in line
            assert ", ." not in line and "  " not in line
            assert line[0].isupper() and line.rstrip().endswith((".", "?"))


def test_the_name_is_not_stapled_on_awkwardly() -> None:
    # "Hey, Shereef, how can I help?" has one pause too many for something
    # meant to sound easy.
    lines = {greeting.opening("Shereef", hour=15, seed=n) for n in range(9)}
    for line in lines:
        assert "Hey, Shereef" not in line


def test_the_same_hour_does_not_always_say_the_same_thing() -> None:
    assert len({greeting.opening("Shereef", hour=9, seed=n) for n in range(9)}) > 1


def test_a_call_is_remembered_for_the_next_one(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(greeting, "LAST_CALL", tmp_path / "state" / "voice-last-call")

    # Nothing remembered yet: the first call of a session is an arrival.
    assert greeting.since_last_call() is None

    greeting.remember_this_call_ended()
    since = greeting.since_last_call()
    assert since is not None and since < 5.0
    assert since < greeting.SAME_CONVERSATION, "an immediate rejoin must read as one"


def test_an_unwritable_state_directory_is_survivable(tmp_path, monkeypatch) -> None:
    # Failing to remember a call must never take the call down.
    monkeypatch.setattr(greeting, "LAST_CALL", tmp_path / "nope" / "\0" / "x")
    greeting.remember_this_call_ended()
    assert greeting.since_last_call() is None


def test_the_name_is_read_the_way_a_person_writes_it(tmp_path) -> None:
    path = tmp_path / "USER.md"
    path.write_text("# About\n\n## Name\n\n- Shereef (he/him)\n\n## Work\n", encoding="utf-8")
    assert greeting.name_from(path) == "Shereef"


def test_a_missing_user_file_is_not_an_error(tmp_path) -> None:
    assert greeting.name_from(tmp_path / "nothing.md") == ""
