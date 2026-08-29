"""Carrying one line across a hung-up call.

Voice sessions have no history: LiveKit starts each one with an empty chat
context, so ending a call and starting another made Marvi a stranger to what
she had been discussing a minute earlier. Memory does not cover this and must
not -- it holds facts, and is told never to store that a conversation happened,
which is exactly why the store stayed clean.
"""

from __future__ import annotations

import time

import pytest

from marvi_gateway import continuity


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    monkeypatch.delenv(continuity.SETTING, raising=False)
    return tmp_path


class Model:
    def __init__(self, said: str) -> None:
        self.said = said


def _answering(monkeypatch, reply: str) -> None:
    monkeypatch.setattr(continuity.distil, "ask", lambda *a, **k: reply)


def test_the_next_session_is_told_what_the_last_one_was_about() -> None:
    continuity.remember("the graph UI in Marvi")

    block = continuity.block()

    assert "the graph UI in Marvi" in block
    # Hedged on purpose: they may have hung up mid-sentence, or moved on.
    assert "only if it fits what they say now" in block


def test_an_old_conversation_is_not_continuity() -> None:
    """A note about three days ago is a non-sequitur, and being reminded of it
    is worse than a cold start."""
    continuity.remember("the graph UI in Marvi")
    saved = continuity._load()
    saved[-1]["at"] = time.time() - (continuity.STALE_HOURS + 1) * 3600
    continuity.path().write_text(__import__("json").dumps(saved), encoding="utf-8")

    assert continuity.recent() == ""
    assert continuity.block() == ""


def test_small_talk_leaves_no_note(monkeypatch) -> None:
    """A session that was nothing in particular should not seed the next one
    with a topic that was never a topic."""
    _answering(monkeypatch, "NOTHING")

    assert continuity.summarise(Model(""), [("hi", "hello")]) == ""
    continuity.remember("NOTHING")
    assert continuity.recent() == ""


def test_a_note_is_one_sentence_not_a_transcript(monkeypatch) -> None:
    """Replaying the last session costs the whole transcript on every turn of
    the next one, and carries every mishearing with it."""
    _answering(monkeypatch, "x" * 5_000)

    note = continuity.summarise(Model(""), [("a", "b")])

    assert len(note) <= continuity.MAX_CHARS


def test_only_the_newest_note_is_shown() -> None:
    continuity.remember("the graph UI")
    continuity.remember("their exam timetable")

    assert "exam timetable" in continuity.block()
    assert "graph UI" not in continuity.block()


def test_it_can_be_switched_off(monkeypatch) -> None:
    continuity.remember("the graph UI")
    monkeypatch.setenv(continuity.SETTING, "off")

    assert continuity.block() == ""


def test_a_summariser_that_fails_costs_the_next_session_a_sentence(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(continuity.distil, "ask", boom)

    assert continuity.summarise(Model(""), [("a", "b")]) == ""
    assert continuity.summarise(None, [("a", "b")]) == ""


def test_the_file_does_not_grow_without_limit() -> None:
    for index in range(continuity.KEEP + 15):
        continuity.remember(f"topic {index}")

    assert len(continuity._load()) == continuity.KEEP
