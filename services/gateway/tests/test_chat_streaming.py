"""Streaming a chat turn.

The measure is not "does the text arrive" but "does the first piece arrive
before the last piece exists". `send` waits for the whole reply before
returning a word, which is a second or more of nothing on chat and the entire
experience of a spoken turn.

Reasoning is asserted to stay separate everywhere. It must not be spoken, must
not reach a TTS, and must not be concatenated into the answer -- doing that
would put a model's private working into Marvi's mouth.
"""

from __future__ import annotations

import json
from typing import ClassVar

import httpx
import pytest

from marvi_gateway.chat import Chat, ChatStore
from marvi_gateway.providers import ProviderClient


def sse(*lines: str) -> str:
    return "".join(f"data: {line}\n" for line in [*lines, "[DONE]"])


def responder(body: str, status: int = 200, seen: list | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        return httpx.Response(
            status, text=body, headers={"content-type": "text/event-stream"}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def chat_with(tmp_path, body: str, **kwargs) -> Chat:
    return Chat(
        store=ChatStore(tmp_path / "chat.sqlite3"),
        client=ProviderClient(http=responder(body)),
        **kwargs,
    )


@pytest.fixture(autouse=True)
def a_provider_to_stream_from(configured):
    """Every test here streams from somewhere, so all of them need one.

    The transport is a mock, but the provider still has to be *chosen*, and
    nothing is chosen unless it is configured. These passed on a machine with a
    real key in its environment and failed on a runner without one.
    """
    configured()


ANSWER = sse(
    '{"choices":[{"delta":{"content":"The "}}]}',
    '{"choices":[{"delta":{"content":"light "}}]}',
    '{"choices":[{"delta":{"content":"is on."}}]}',
    '{"usage":{"prompt_tokens":10,"completion_tokens":4}}',
)


def test_each_token_arrives_on_its_own(tmp_path) -> None:
    """Not one delta carrying the finished sentence."""
    events = list(chat_with(tmp_path, ANSWER).send_stream("is the light on?"))

    deltas = [e["delta"] for e in events if "delta" in e]

    assert deltas == ["The ", "light ", "is on."]


def test_the_reply_is_assembled_for_the_transcript(tmp_path) -> None:
    """Streamed to the window, whole in the history."""
    events = list(chat_with(tmp_path, ANSWER).send_stream("is the light on?"))

    done = events[-1]

    assert done["done"] is True
    assert done["reply"] == "The light is on."
    assert done["error"] == ""


def test_reasoning_is_a_separate_event_and_never_the_answer(tmp_path) -> None:
    """The one thing that must not leak into what Marvi says."""
    body = sse(
        '{"choices":[{"delta":{"reasoning":"the user asked about the light"}}]}',
        '{"choices":[{"delta":{"content":"Yes."}}]}',
    )

    events = list(chat_with(tmp_path, body).send_stream("is it on?"))

    kinds = [next(iter(e)) for e in events]
    assert kinds[0] == "reasoning", "thinking arrives before the answer"
    assert [e["delta"] for e in events if "delta" in e] == ["Yes."]
    assert "the user asked" not in events[-1]["reply"]


def test_openrouter_reasoning_details_are_understood(tmp_path) -> None:
    """The shape OpenRouter actually documents for streamed reasoning."""
    body = sse(
        '{"choices":[{"delta":{"reasoning_details":'
        '[{"type":"reasoning.text","text":"step one"}]}}]}',
        '{"choices":[{"delta":{"content":"Done."}}]}',
    )

    events = list(chat_with(tmp_path, body).send_stream("go"))

    assert any(e.get("reasoning") == "step one" for e in events)


def test_a_tool_call_is_reassembled_from_its_fragments(tmp_path) -> None:
    """Arguments are only valid JSON once the last fragment lands."""
    calls: list[tuple] = []

    def dispatch(name, arguments):
        calls.append((name, arguments))
        return {"status": "executed", "result": "on"}

    body = sse(
        '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
        '"function":{"name":"set_light"}}]}}]}',
        '{"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"{\\"on\\":"}}]}}]}',
        '{"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"true}"}}]}}]}',
    )

    events = list(chat_with(tmp_path, body, dispatch=dispatch).send_stream("light on"))

    # This fake answers every round with the same call, so it loops to the
    # bound; what is under test is that the fragments became one valid call.
    assert calls[0] == ("set_light", {"on": True})
    assert all(call == calls[0] for call in calls)
    assert any(e.get("tool") == "set_light" for e in events)


def test_a_confirmation_stops_the_turn(tmp_path) -> None:
    """The action has not happened, and must not be narrated as though it had."""

    def dispatch(name, arguments):
        return {"status": "confirmation_required", "token": "tok-1"}

    body = sse(
        '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
        '"function":{"name":"send_email","arguments":"{}"}}]}}]}',
    )

    events = list(chat_with(tmp_path, body, dispatch=dispatch).send_stream("email them"))

    done = events[-1]
    assert done["done"] is True
    assert done["pending_confirmation"]["tool"] == "send_email"
    assert done["reply"] == "", "nothing may be claimed before it is confirmed"


def test_an_empty_message_ends_immediately(tmp_path) -> None:
    events = list(chat_with(tmp_path, ANSWER).send_stream("   "))

    assert events == [
        {"done": True, "error": "empty message", "tokens": 0, "provider": ""}
    ]


def test_a_provider_that_cannot_start_is_reported(tmp_path) -> None:
    """Fallback happens before the first delta; after it, failure is honest."""
    chat = Chat(
        store=ChatStore(tmp_path / "chat.sqlite3"),
        client=ProviderClient(http=responder("", status=500)),
    )

    done = list(chat.send_stream("hello"))[-1]

    assert done["done"] is True
    assert done["error"]


def test_the_turn_is_timed_with_a_real_first_token(tmp_path, monkeypatch) -> None:
    """Chat can finally be compared with voice on the measure that matters.

    The blocking path records `first_token_ms` as None, because there is no
    first token to time when the whole reply arrives at once.
    """
    from marvi_gateway import latency

    recording = tmp_path / "latency.jsonl"
    monkeypatch.setattr(latency, "recording_path", lambda: recording)

    list(chat_with(tmp_path, ANSWER).send_stream("is the light on?"))

    import json

    rows = [json.loads(line) for line in recording.read_text().splitlines() if line.strip()]
    assert rows, "a streamed turn must be recorded"
    assert rows[-1]["first_token_ms"] is not None
    assert rows[-1]["path"] == "stream"


@pytest.mark.parametrize("field", ["reasoning", "reasoning_content"])
def test_the_other_reasoning_field_names_are_understood(tmp_path, field: str) -> None:
    """OpenRouter sends `reasoning`; DeepSeek calls it `reasoning_content`."""
    body = sse(
        '{"choices":[{"delta":{' + f'"{field}"' + ':"mulling"}}]}',
        '{"choices":[{"delta":{"content":"ok"}}]}',
    )

    events = list(chat_with(tmp_path, body).send_stream("go"))

    assert any(e.get("reasoning") == "mulling" for e in events)


# -- cancellation ------------------------------------------------------------


def test_a_cancelled_turn_stops_asking_the_provider(tmp_path) -> None:
    """An abandoned stream that keeps generating is billed in full.

    The window closes, the reader goes away, and without this the provider
    carries on writing an answer nobody will ever see -- and charges for it.
    Cancelling closes the connection rather than draining it.
    """
    body = sse(*[f'{{"choices":[{{"delta":{{"content":"word{n} "}}}}]}}' for n in range(50)])
    chat = Chat(
        store=ChatStore(tmp_path / "chat.sqlite3"),
        client=ProviderClient(http=responder(body)),
    )

    delivered = 0

    def cancelled() -> bool:
        # Give up after a few words, the way a person closing a window does.
        return delivered >= 3

    events = []
    for event in chat.send_stream("go", cancelled=cancelled):
        events.append(event)
        if "delta" in event:
            delivered += 1

    done = events[-1]
    assert done["cancelled"] is True
    assert done["error"] == "", "cancelling is not a failure"
    assert sum(1 for e in events if "delta" in e) < 10, "the other forty were never read"


def test_what_arrived_before_a_cancel_is_kept(tmp_path) -> None:
    """Half an answer is still worth keeping; it was already on screen."""
    body = sse(*[f'{{"choices":[{{"delta":{{"content":"w{n} "}}}}]}}' for n in range(20)])
    chat = Chat(
        store=ChatStore(tmp_path / "chat.sqlite3"),
        client=ProviderClient(http=responder(body)),
    )

    seen = 0

    def cancelled() -> bool:
        return seen >= 2

    events = []
    for event in chat.send_stream("go", cancelled=cancelled):
        events.append(event)
        if "delta" in event:
            seen += 1

    assert events[-1]["reply"].startswith("w0")


def test_a_turn_nobody_cancels_runs_to_the_end(tmp_path) -> None:
    """The guard must not fire on its own."""
    events = list(chat_with(tmp_path, ANSWER).send_stream("go"))

    assert events[-1].get("cancelled") is not True
    assert events[-1]["reply"] == "The light is on."


# -- what the model remembers of its own actions -----------------------------


def rounds(bodies: list, *replies: str) -> httpx.Client:
    """A provider that answers each round from `replies`, recording requests."""
    seen = iter(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, text=next(seen), headers={"content-type": "text/event-stream"}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


CALL = sse(
    '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
    '"function":{"name":"set_light","arguments":"{\\"on\\":true}"}}]}}]}'
)


def test_the_model_is_told_what_it_already_called(tmp_path) -> None:
    """Otherwise it calls the same tool again, and again, to the round limit.

    Only the tool *result* was replayed, as an observation with no author. The
    model's own decision to call the tool was never recorded, so on the next
    round it saw a result it had no memory of asking for -- and asked again.
    Eight rounds of that is eight round trips and eight times the tokens for
    one answer.
    """
    bodies: list = []
    chat = Chat(
        store=ChatStore(tmp_path / "chat.sqlite3"),
        client=ProviderClient(http=rounds(bodies, CALL, ANSWER)),
        dispatch=lambda name, arguments: {"status": "executed", "result": "on"},
    )

    list(chat.send_stream("turn the light on"))

    assert len(bodies) == 2, "the fake answers a call then an answer"
    second = bodies[1]["messages"]
    assistant = [m for m in second if m["role"] == "assistant"]

    assert assistant, "round two shows no record of the model having acted"
    assert "set_light" in " ".join(m["content"] for m in assistant)


def test_the_tool_result_is_still_replayed(tmp_path) -> None:
    """The record of the call must not displace what the call returned."""
    bodies: list = []
    chat = Chat(
        store=ChatStore(tmp_path / "chat.sqlite3"),
        client=ProviderClient(http=rounds(bodies, CALL, ANSWER)),
        dispatch=lambda name, arguments: {"status": "executed", "result": "the light is on"},
    )

    list(chat.send_stream("turn the light on"))

    assert "the light is on" in json.dumps(bodies[1]["messages"])


def test_what_the_plugins_already_know_reaches_the_prompt(tmp_path) -> None:
    """`plugins.context_lines` existed, was documented, and had no caller.

    The room engine offers a context line carrying its own vision block --
    whether the owner is visible, what they appear to be doing. Marvi collected
    the provider and never called it, so it ran a second camera pipeline while
    ignoring the answer it already had.
    """

    class Plugin:
        name = "room"

        class context:  # noqa: N801 - mirrors the plugin contract's shape
            context_providers: ClassVar = {"room": lambda: "the owner is at the desk"}

    bodies: list = []
    chat = Chat(
        store=ChatStore(tmp_path / "chat.sqlite3"),
        client=ProviderClient(http=rounds(bodies, ANSWER)),
        plugins=[Plugin()],
    )

    list(chat.send_stream("what am I doing?"))

    assert "the owner is at the desk" in bodies[0]["messages"][0]["content"]


def test_a_plugin_that_throws_does_not_take_the_turn_down(tmp_path) -> None:
    class Broken:
        name = "broken"

        class context:  # noqa: N801
            context_providers: ClassVar = {"boom": lambda: 1 / 0}

    bodies: list = []
    chat = Chat(
        store=ChatStore(tmp_path / "chat.sqlite3"),
        client=ProviderClient(http=rounds(bodies, ANSWER)),
        plugins=[Broken()],
    )

    assert list(chat.send_stream("hello"))[-1]["reply"] == "The light is on."


def test_the_streaming_path_still_learns_and_asks(tmp_path) -> None:
    """It did not, from the moment streaming became the path chat takes.

    `send` ran the curiosity turn; `send_stream` passed a null gap and never
    called `learn` or `may_ask`. So Marvi stopped noticing a name offered
    plainly and stopped ever asking its one question, silently.
    """
    from marvi_gateway.curiosity import Curiosity
    from marvi_gateway.identity import IdentityFiles

    curiosity = Curiosity(
        path=tmp_path / "curiosity.sqlite3",
        identity=IdentityFiles(directory=tmp_path / "identity"),
    )
    bodies: list = []
    chat = Chat(
        store=ChatStore(tmp_path / "chat.sqlite3"),
        client=ProviderClient(http=rounds(bodies, ANSWER)),
        curiosity=curiosity,
    )

    list(chat.send_stream("my name is Sam"))

    assert curiosity.state()["name"]["value"] == "Sam", "a name said plainly was not learnt"
