"""Looking the memory up while the user is still speaking.

Recall must finish before the model starts, because it changes what the model
sees. Done when the user stops speaking, its whole cost sits in front of the
reply: measured at 179ms of the 950ms to first token. Done during the speaking,
it costs nothing, because there is something to hide it behind.

The bet is that an interim transcript is a good enough query for the sentence it
becomes -- the memories matching "what computer am I runni" are the memories
matching "what computer am I running you on". These are the cases where that
bet is right, and the ones where it is not.
"""

from __future__ import annotations

import time

import pytest

from marvi_agent import session as session_module


@pytest.fixture
def prefetch(monkeypatch):
    """A prefetcher whose lookups are instant and recorded."""
    asked: list[str] = []
    readings: list[bool] = []

    def fake_recall(text: str, *, read: bool = False) -> str:
        asked.append(text)
        readings.append(read)
        return f"block for {text}"

    monkeypatch.setattr(session_module, "_recall", fake_recall)
    found = session_module._Prefetch()
    found.asked = asked  # type: ignore[attr-defined]
    found.readings = readings  # type: ignore[attr-defined]
    return found


def settle(prefetch) -> None:
    """Wait for the background thread. Deliberately not a sleep in the code
    under test -- only the test knows it is waiting for one."""
    for _ in range(200):
        if prefetch._block or prefetch._query:
            return
        time.sleep(0.005)


def test_the_finished_sentence_uses_what_was_fetched_mid_word(prefetch) -> None:
    prefetch.begin("what computer am I runni")
    settle(prefetch)

    assert prefetch.take("what computer am I running you on") == "block for what computer am I runni"
    assert prefetch.hits == 1


def test_a_different_sentence_is_not_answered_with_the_old_one(prefetch) -> None:
    """The bet is that words get appended, not rewritten. When the recogniser
    changes its mind, the prefetched block belongs to a sentence nobody said."""
    prefetch.begin("what computer am I using")
    settle(prefetch)

    assert prefetch.take("where do I live") is None
    assert prefetch.misses == 1


def test_a_miss_costs_only_the_wasted_lookup(prefetch) -> None:
    """`None` means fetch it live, which is what the turn did before any of
    this existed. A miss must never mean a turn without memory."""
    assert prefetch.take("anything at all") is None


def test_it_is_used_once(prefetch) -> None:
    """The next turn is a different sentence. A block left behind would be
    applied to it, and a memory answer to the wrong question is worse than
    none."""
    prefetch.begin("what computer am I runni")
    settle(prefetch)

    assert prefetch.take("what computer am I running you on") is not None
    assert prefetch.take("what computer am I running you on") is None


def test_a_stale_answer_is_not_used(prefetch, monkeypatch) -> None:
    """A turn is seconds. Anything older belongs to a sentence that has already
    been answered."""
    prefetch.begin("what computer am I runni")
    settle(prefetch)
    monkeypatch.setattr(
        session_module.time, "monotonic", lambda: prefetch._at + prefetch.FRESH + 1
    )

    assert prefetch.take("what computer am I running you on") is None


def test_a_fragment_is_not_worth_a_search(prefetch) -> None:
    """A recogniser emits "wh" before it emits anything useful, and the
    memories matching two letters are not the memories matching the sentence."""
    prefetch.begin("what")
    time.sleep(0.05)

    assert prefetch.asked == []


def test_one_lookup_at_a_time(prefetch) -> None:
    """A recogniser emits many interims a second, each a superset of the last.
    Firing on every one would be a search per word; the prefix test accepts an
    earlier answer anyway, so the first is worth as much as the newest.
    """
    for text in (
        "what computer am I",
        "what computer am I running",
        "what computer am I running you on",
    ):
        prefetch.begin(text)
    settle(prefetch)

    assert len(prefetch.asked) == 1


def test_the_prefetch_is_what_pays_for_a_reading(prefetch) -> None:
    """A model reading the memories costs ~600ms and answers the questions the
    search ranks wrongly. The prefetch window is 1,789ms at the median over 121
    real turns, so asking here is free; asking on the live path would put it in
    front of a turn that is already waiting."""
    prefetch.begin("what computer am I runni")
    settle(prefetch)

    assert prefetch.readings == [True]


def test_a_prefetch_that_found_nothing_is_a_miss_not_an_answer(monkeypatch) -> None:
    """The recogniser cuts interims mid-word, and a cut sentence matches
    nothing that the whole one matches.

    A real session prefetched "You have a clar" and "Do you t can you tell me
    what games" -- both empty against the live store -- while the sentences
    they became match 905 and 482 characters. Handing the empty string back as
    though it were the answer meant `_recall` never ran on the finished
    sentence, so those turns reached the model with no memory at all and Marvi
    denied knowing things she had been told minutes before.
    """
    def nothing(text: str, *, read: bool = False) -> str:
        return ""

    monkeypatch.setattr(session_module, "_recall", nothing)
    prefetch = session_module._Prefetch()
    prefetch.begin("You have a clar")
    for _ in range(200):
        if prefetch._query:
            break
        time.sleep(0.005)

    assert prefetch.take("You have a clarification tool for info.") is None
    assert prefetch.misses == 1


def test_an_empty_lookup_does_not_claim_the_last_turn_s_block(prefetch, monkeypatch) -> None:
    """`staged` only asks whether the text starts with the query, and every
    fragment of a new sentence starts one. A lookup that found nothing left
    the previous turn's block flagged as staged for this one, so the turn was
    answered from the wrong memories and the log said so: "already in
    context", on a sentence nothing had been staged for."""
    prefetch.begin("what computer am I runni")
    settle(prefetch)
    prefetch._installed = True

    monkeypatch.setattr(session_module, "_recall", lambda text, *, read=False: "")
    prefetch._query = ""
    prefetch.begin("anything about this?")
    for _ in range(200):
        if prefetch._query == "anything about this?":
            break
        time.sleep(0.005)

    assert prefetch.staged("anything about this?") is False
