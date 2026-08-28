"""Deciding what to keep, after the turn, with an operation rather than an append.

Three faults, one shape: the model did it, mid-conversation, by hand.

* it happened *during* the turn, so being remembered cost the user latency;
* it stored whatever the model typed, which is how `Hi Sharif.` became an
  episodic memory whose subject was "Hello" -- her own reply, filed as a fact;
* it could only add, so a correction joined the thing it corrected.

Mem0's four operations are the fix for the third, and the reason to copy that
shape is that it is the failure their design exists to prevent.
"""

from __future__ import annotations

from typing import Any

import pytest

from marvi_gateway import remembering
from marvi_gateway.memory import MemoryStore


class Reply:
    def __init__(self, text: str) -> None:
        self.text = text


class Model:
    """A provider that answers with whatever operations a test wants."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    def call_with_fallback(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return Reply(self.answer)


@pytest.fixture
def store(tmp_path):
    made = MemoryStore(tmp_path / "memory.sqlite3")
    yield made
    made.close()


# -- the operations ----------------------------------------------------------


def test_add_stores_a_fact(store) -> None:
    model = Model('[{"op":"add","subject":"coffee","body":"The user drinks it black.","kind":"semantic"}]')

    done = remembering.extract(store, model, "I take it black", "Noted.")

    assert done["add"] == 1
    assert "black" in store.recent(limit=5)[0]["body"]


def test_update_replaces_rather_than_joins(store) -> None:
    """The whole point. A correction that is added sits beside the thing it was
    meant to replace, and both come back on recall."""
    first = store.remember("city", "The user lives in Alexandria.", kind="semantic")
    model = Model(f'[{{"op":"update","id":{first},"subject":"city","body":"The user lives in Cairo."}}]')

    done = remembering.extract(store, model, "I moved to Cairo", "Got it.")

    kept = store.recent(limit=10)
    assert done["update"] == 1
    assert len(kept) == 1
    assert "Cairo" in kept[0]["body"]


def test_a_model_can_catch_what_string_matching_cannot(store) -> None:
    """Alexandria and Cairo share no significant words, so the similarity floor
    underneath would have kept both. This is why the operation is chosen by a
    model rather than by an overlap score."""
    first = store.remember("city", "The user lives in Alexandria.", kind="semantic")
    store.remember("city", "The user lives in Cairo.", kind="semantic")
    assert len(store.recent(limit=10)) == 2, "the floor cannot catch this on its own"

    model = Model(f'[{{"op":"delete","id":{first}}}]')
    done = remembering.extract(store, model, "I moved", "Got it.")

    assert done["delete"] == 1
    assert len(store.recent(limit=10)) == 1


def test_an_empty_answer_stores_nothing(store) -> None:
    """The right answer most of the time. A store that keeps something from
    every exchange is a transcript."""
    done = remembering.extract(store, Model("[]"), "hello", "Hi there.")

    assert done == {"add": 0, "update": 0, "delete": 0, "ignored": 0, "noted": []}
    assert store.recent(limit=5) == []


def test_the_model_is_shown_what_is_already_known(store) -> None:
    """It cannot choose `update` over `add` without seeing what to update."""
    store.remember("city", "The user lives in Alexandria.", kind="semantic")
    model = Model("[]")

    remembering.extract(store, model, "I moved to Cairo", "Got it.")

    assert "Alexandria" in model.calls[0]["messages"][1]["content"]


def test_it_asks_the_memory_role(store) -> None:
    """Not the conversation model. This is short, unattended, and needs no
    reasoning -- which is what the auxiliary roles are for."""
    model = Model("[]")

    remembering.extract(store, model, "hello", "Hi.")

    assert model.calls[0]["job"] == "aux"


# -- surviving bad answers ---------------------------------------------------


def test_prose_around_the_json_is_tolerated(store) -> None:
    """Models wrap JSON in explanation and in code fences, routinely."""
    model = Model('Sure! ```json\n[{"op":"add","subject":"tea","body":"The user prefers tea."}]\n```')

    assert remembering.extract(store, model, "I prefer tea", "Noted.")["add"] == 1


def test_an_unparseable_answer_keeps_nothing_and_does_not_raise(store) -> None:
    """This runs on a worker thread behind a queue. A thread that dies takes
    every later turn with it, so nothing here may throw."""
    assert remembering.extract(store, Model("I could not decide."), "x", "y")["add"] == 0


def test_no_model_means_nothing_is_written(store) -> None:
    """Degrades to remembering nothing rather than to remembering wrongly."""
    assert remembering.extract(store, None, "hello", "Hi.")["add"] == 0
    assert store.recent(limit=5) == []


def test_an_unknown_operation_is_ignored_rather_than_guessed(store) -> None:
    model = Model('[{"op":"merge","id":1,"body":"..."}]')

    assert remembering.extract(store, model, "x", "y")["ignored"] == 1


# -- off the turn ------------------------------------------------------------


def test_observing_returns_immediately_and_works_in_the_background(store) -> None:
    """The queue is the point, not an optimisation: nothing a user waits for is
    behind this."""
    model = Model('[{"op":"add","subject":"tea","body":"The user prefers tea to coffee."}]')
    worker = remembering.Rememberer(store, model)

    assert worker.observe("I prefer tea", "Noted.") is True
    assert worker.drain(timeout=5.0), "the worker should finish promptly"
    assert any("tea" in row["body"] for row in store.recent(limit=5))


def test_a_full_queue_drops_rather_than_blocks(store, monkeypatch) -> None:
    """Falling behind on memory is survivable. Blocking a reply on it is not."""
    monkeypatch.setattr(remembering, "QUEUE_DEPTH", 1)

    class Slow(Model):
        def call_with_fallback(self, messages, **kwargs):
            import time

            time.sleep(0.5)
            return Reply("[]")

    worker = remembering.Rememberer(store, Slow("[]"))
    accepted = [worker.observe(f"turn {n}", "ok") for n in range(6)]

    assert accepted[0] is True
    assert False in accepted, "a full queue must refuse rather than wait"

def test_the_worker_is_handed_a_client_it_can_actually_call(tmp_path, monkeypatch) -> None:
    """It was handed the harness instead of the harness's client.

    `CognitionHarness` runs a tool loop and has no `call_with_fallback`, so
    every extraction raised AttributeError into the worker's own broad except,
    which logged "extraction unavailable" at info level and kept nothing. The
    store on the developer's machine held a single memory, written by hand
    through the tool, while this had been shipped and believed to work.

    Nothing caught it because every test in this file passes its own fake
    client. Unit tests cannot see a wiring mistake; this looks at what the app
    actually builds.
    """
    from fastapi.testclient import TestClient

    from marvi_gateway.app import create_app

    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    with TestClient(create_app()) as client:
        worker = client.app.state.rememberer

    assert worker is not None
    assert _usable(worker._client)


def test_the_dreamer_is_handed_one_too(tmp_path, monkeypatch) -> None:
    """Same wiring, same mistake available: dreaming calls the same method on
    whatever the scheduler was given."""
    from fastapi.testclient import TestClient

    from marvi_gateway.app import create_app

    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    with TestClient(create_app()) as client:
        initiative = getattr(client.app.state, "initiative", None)

    if initiative is None or initiative.auxiliary_client is None:
        return
    assert _usable(initiative.auxiliary_client)


def _usable(client: object) -> bool:
    """Whether `distil.ask` can actually make a call with this.

    The two shapes it knows: the harness, or the provider client underneath it.
    Anything else reaches the model through nothing and fails into a log line.
    """
    from marvi_gateway.cognition import CognitionHarness

    return isinstance(client, CognitionHarness) or callable(
        getattr(client, "call_with_fallback", None)
    )


def test_marvi_is_told_what_the_worker_wrote_down(tmp_path, monkeypatch) -> None:
    """The worker runs off the turn, which is right -- a memory decision must
    not sit in front of a spoken reply. But it left her unaware anything had
    been written: she could not say she had noted something, and could not be
    corrected about it while the user still remembered saying it.
    """
    from fastapi.testclient import TestClient

    from marvi_gateway.app import create_app

    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    with TestClient(create_app()) as client:
        worker = client.app.state.rememberer
        worker.noted = ["the bakery night shift"]

        block = client.get("/memory/recall", params={"text": "hello"}).json()["block"]

    assert "you wrote down: the bakery night shift" in block


def test_it_is_said_once(tmp_path, monkeypatch) -> None:
    """On the turn after it was written and on no turn after that. Repeating
    would have her announcing the same memory until something replaced it."""
    from fastapi.testclient import TestClient

    from marvi_gateway.app import create_app

    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    with TestClient(create_app()) as client:
        client.app.state.rememberer.noted = ["the bakery night shift"]
        first = client.get("/memory/recall", params={"text": "hello"}).json()["block"]
        second = client.get("/memory/recall", params={"text": "hello"}).json()["block"]

    assert "you wrote down" in first
    assert "you wrote down" not in second


def test_what_was_written_is_named_not_counted(tmp_path) -> None:
    """"I noted 2 things" is not something a person can correct."""
    from marvi_gateway import remembering
    from marvi_gateway.memory import MemoryStore

    store = MemoryStore(tmp_path / "m.db")
    done = remembering.apply(
        store,
        [{"op": "add", "subject": "bakery", "body": "The user works nights.", "kind": "semantic"}],
    )

    assert done["noted"] == ["bakery"]
