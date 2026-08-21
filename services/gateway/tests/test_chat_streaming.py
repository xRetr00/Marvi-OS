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
        '{"choices":[{"delta":{"%s":"mulling"}}]}' % field,
        '{"choices":[{"delta":{"content":"ok"}}]}',
    )

    events = list(chat_with(tmp_path, body).send_stream("go"))

    assert any(e.get("reasoning") == "mulling" for e in events)
