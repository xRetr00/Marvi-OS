"""Questions Chat asks inside a turn.

The bug these exist for: `clarify` and `ask_secret` posted to the voice surface
whoever asked, so asking in Chat drew a card on the Dynamic Island and left the
transcript empty. Chat now answers both itself and waits for the result, and
the thing worth pinning down is that waiting can end three ways -- answered,
abandoned, cancelled -- and that a secret never comes back through any of them.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from marvi_gateway.inline_ask import ASKS, InlineAsk, InlineAsks


@pytest.fixture
def asks():
    store = InlineAsks()
    yield store
    store.forget()


def opened(store: InlineAsks, **fields) -> InlineAsk:
    base = {"id": "q1", "kind": "clarify", "question": "Which one?", "asked_at": 1e9}
    return store.open(InlineAsk(**{**base, **fields}))


def test_an_answer_wakes_the_waiting_turn(asks) -> None:
    ask = opened(asks)
    threading.Timer(0.05, lambda: asks.settle(ask.id, "the second one")).start()

    assert asks.wait(ask.id, timeout=5.0) == "the second one"


def test_a_question_nobody_answers_times_out_rather_than_hanging(asks) -> None:
    ask = opened(asks)

    assert asks.wait(ask.id, timeout=0.3) is None


def test_a_cancelled_turn_stops_waiting(asks) -> None:
    """A closed window sets the turn's cancel flag. Waiting out the full five
    minutes on a turn nobody is watching would pin a worker thread for it."""
    ask = opened(asks)

    assert asks.wait(ask.id, cancelled=lambda: True, timeout=30.0) is None


def test_waiting_clears_the_question_either_way(asks) -> None:
    ask = opened(asks)
    asks.wait(ask.id, timeout=0.1)

    assert asks.waiting() == []
    assert asks.settle(ask.id, "too late") is False


def test_settling_something_nobody_waits_on_is_a_miss_not_a_crash(asks) -> None:
    assert asks.settle("never-existed", "hello") is False


def test_only_live_questions_are_listed(asks) -> None:
    opened(asks, id="fresh", asked_at=__import__("time").time())
    opened(asks, id="ancient", asked_at=1.0)

    assert [ask.id for ask in asks.waiting()] == ["fresh"]


# -- the route ---------------------------------------------------------------


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    from marvi_gateway.app import create_app

    ASKS.forget()
    with TestClient(create_app()) as running:
        yield running
    ASKS.forget()


def test_the_window_can_hand_an_answer_back(client) -> None:
    ask = ASKS.open(InlineAsk(id="q9", kind="clarify", question="Which?", asked_at=1e9))
    done = threading.Event()
    answer: list[str | None] = []

    def turn() -> None:
        answer.append(ASKS.wait(ask.id, timeout=5.0))
        done.set()

    threading.Thread(target=turn).start()

    assert client.post("/chat/ask/q9", json={"answer": "the second"}).status_code == 200
    assert done.wait(5.0)
    assert answer == ["the second"]


def test_an_empty_answer_is_refused(client) -> None:
    ASKS.open(InlineAsk(id="q8", kind="clarify", question="Which?", asked_at=1e9))

    assert client.post("/chat/ask/q8", json={"answer": "   "}).status_code == 400


def test_answering_a_turn_that_moved_on_says_so(client) -> None:
    """409, not 404. The window has to tell "never existed" from "too late" to
    know whether retrying could ever work."""
    assert client.post("/chat/ask/gone", json={"answer": "hi"}).status_code == 409


def test_waiting_questions_are_listed_for_a_window_that_reconnects(client) -> None:
    import time

    ASKS.open(InlineAsk(id="q7", kind="secret", name="SMTP_PASSWORD", asked_at=time.time()))

    body = client.get("/chat/ask").json()

    assert [ask["id"] for ask in body["waiting"]] == ["q7"]
    assert body["waiting"][0]["name"] == "SMTP_PASSWORD"
