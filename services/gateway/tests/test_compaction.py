"""What a long conversation remembers about its own beginning.

The window has always been the last `HISTORY_TURNS` exchanges, so a long
conversation did not overflow -- it forgot. The twenty-fifth turn could not see
the first, and the person could, which is the version of forgetting that looks
like not listening.
"""

from __future__ import annotations

import pytest

from marvi_gateway.chat import HISTORY_TURNS, Chat, ChatStore


class FakeSummariser:
    """Stands in for the auxiliary model `distil.earlier` would call."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def call_with_fallback(self, messages, **_kwargs):
        self.asked.append(str(messages[-1]["content"]))

        class Answer:
            text = "They planned a trip to Alexandria and booked a hotel."

        return Answer()


def _thread(tmp_path, turns: int):
    store = ChatStore(tmp_path / "chat.db")
    thread = store.create_thread("Long one")["id"]
    for n in range(turns):
        store.append("user", f"question {n}", thread_id=thread)
        store.append("assistant", f"answer {n}", thread_id=thread)
    return store, thread


def test_nothing_is_summarised_while_it_all_still_fits(tmp_path) -> None:
    store, thread = _thread(tmp_path, HISTORY_TURNS - 1)
    talk = Chat(store=store, client=FakeSummariser())

    assert talk.compact(thread) == ""
    assert store.summary_of(thread) == {}


def test_what_scrolls_out_is_summarised_and_reaches_the_next_turn(tmp_path) -> None:
    store, thread = _thread(tmp_path, HISTORY_TURNS + 6)
    model = FakeSummariser()
    talk = Chat(store=store, client=model)

    said = talk.compact(thread)

    assert "Alexandria" in said
    held = store.summary_of(thread)
    assert held["summary"] == said and held["through_id"] > 0
    # The turns that fell out were summarised, not the whole thread.
    assert "question 0" in model.asked[0]
    assert f"question {HISTORY_TURNS + 5}" not in model.asked[0]

    # And the next turn carries it.
    wire = talk._messages(thread_id=thread)
    assert any("Earlier in this conversation" in str(one.get("content")) for one in wire)


def test_a_second_pass_folds_into_the_first(tmp_path) -> None:
    store, thread = _thread(tmp_path, HISTORY_TURNS + 2)
    model = FakeSummariser()
    talk = Chat(store=store, client=model)
    talk.compact(thread)
    first_through = store.summary_of(thread)["through_id"]

    # Nothing new has fallen out, so the model is not asked again.
    assert talk.compact(thread) == ""
    assert len(model.asked) == 1

    for n in range(4):
        store.append("user", f"later {n}", thread_id=thread)
        store.append("assistant", f"reply {n}", thread_id=thread)
    talk.compact(thread)

    assert store.summary_of(thread)["through_id"] > first_through
    assert "The summary so far:" in model.asked[1]


def test_a_model_that_fails_leaves_the_conversation_working(tmp_path) -> None:
    class Broken:
        def call_with_fallback(self, *_args, **_kwargs):
            raise RuntimeError("no model")

    store, thread = _thread(tmp_path, HISTORY_TURNS + 3)
    assert Chat(store=store, client=Broken()).compact(thread) == ""
    assert store.summary_of(thread) == {}


def test_the_originals_are_never_touched(tmp_path) -> None:
    """Compaction is what the *model* sees, not what the person's history is."""
    store, thread = _thread(tmp_path, HISTORY_TURNS + 4)
    Chat(store=store, client=FakeSummariser()).compact(thread)

    rows = store._db.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE thread_id = ?", (thread,)
    ).fetchone()["n"]
    assert rows == (HISTORY_TURNS + 4) * 2
    assert len(store.search("question 0")) == 1  # still findable


def test_the_turn_wrapper_takes_the_arguments_the_gateway_passes(tmp_path) -> None:
    """The regression that hid behind 2,029 passing tests.

    `/chat/stream` calls `send_stream(message, provider, model, effort, ...)`
    positionally. Wrapping the turn for hooks and compaction with a
    `**options` signature broke the chat window and nothing failed, because
    every test passed keywords.
    """
    import inspect

    from marvi_gateway.chat import Chat

    taken = list(inspect.signature(Chat.send_stream).parameters)
    assert taken[:5] == ["self", "message", "provider", "model", "effort"]
    assert taken == list(inspect.signature(Chat._send_stream).parameters)

    # And it really runs that way, not just declares it.
    store = ChatStore(tmp_path / "chat.db")
    events = list(Chat(store=store).send_stream("hello", "openai", "gpt-5.2", "low"))
    assert events and events[-1]["done"] is True


@pytest.mark.asyncio
async def test_folding_can_be_asked_for_by_hand(monkeypatch, tmp_path) -> None:
    """`/compress` in the chat composer.

    Folding happens by itself after a turn. The reason to ask for it is the
    moment before a long one -- and asking twice has to be safe, because the
    composer has no way to know whether anything has scrolled out since.
    """
    from httpx import ASGITransport, AsyncClient

    from marvi_gateway.app import create_app

    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        made = await client.post("/chat/threads", json={"title": "Long one"})
        thread = made.json()["id"]

        folded = await client.post(f"/chat/threads/{thread}/compact")

        assert folded.status_code == 200
        # Nothing has scrolled out of a new thread, so it says so rather than
        # calling a model to summarise nothing.
        assert folded.json() == {"folded": False, "summary": ""}
        assert (await client.post(f"/chat/threads/{thread}/compact")).status_code == 200
