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

    def fake_recall(text: str) -> str:
        asked.append(text)
        return f"block for {text}"

    monkeypatch.setattr(session_module, "_recall", fake_recall)
    found = session_module._Prefetch()
    found.asked = asked  # type: ignore[attr-defined]
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
