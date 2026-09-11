"""What Marvi did on the way to an answer.

Before this the trace did not exist anywhere a person could see it. Tool calls
were stored as hidden rows, the window was told only a tool's *name*, and any
text the model wrote before calling a tool was thrown away at the end of the
round -- so a turn that searched, read two pages and patched a file arrived as
a spinner followed by an answer, and reopening the thread showed even less.

These pin three things: the window is told enough to draw each call as it
happens, the reply is stored with the whole trace in the order it happened,
and the answer text is not polluted by the commentary that preceded it.
"""

from __future__ import annotations

import httpx
import pytest

from marvi_gateway.chat import Chat, ChatStore, TRACE_RESULT_CHARS
from marvi_gateway.providers import ProviderClient


def sse(*lines: str) -> str:
    return "".join(f"data: {line}\n" for line in [*lines, "[DONE]"])


def rounds(*bodies: str) -> httpx.Client:
    """A provider that answers each request with the next body in turn."""
    queue = iter(bodies)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=next(queue), headers={"content-type": "text/event-stream"})

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def a_provider_to_stream_from(configured):
    configured()


# Round one: a thought, a line of commentary, then a tool call.
LOOKS = sse(
    '{"choices":[{"delta":{"reasoning":"The user wants the room state."}}]}',
    '{"choices":[{"delta":{"content":"Let me check the room."}}]}',
    '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
    '"function":{"name":"room_state","arguments":"{\\"detail\\":true}"}}]}}]}',
)

# Round two: another thought, then the answer.
ANSWERS = sse(
    '{"choices":[{"delta":{"reasoning":"The light is off."}}]}',
    '{"choices":[{"delta":{"content":"The light is off."}}]}',
    '{"usage":{"prompt_tokens":40,"completion_tokens":6}}',
)


def chat(tmp_path, dispatch) -> Chat:
    return Chat(
        store=ChatStore(tmp_path / "chat.sqlite3"),
        client=ProviderClient(http=rounds(LOOKS, ANSWERS)),
        dispatch=dispatch,
    )


def test_the_window_is_told_what_each_call_was_and_what_it_returned(tmp_path) -> None:
    events = list(
        chat(tmp_path, lambda name, arguments: {"status": "ok", "result": "light: off"}).send_stream(
            "what is the room doing?"
        )
    )

    started = [e["tool_call"] for e in events if "tool_call" in e]
    finished = [e["tool_result"] for e in events if "tool_result" in e]

    assert started == [{"id": "c1", "name": "room_state", "arguments": {"detail": True}}]
    assert finished[0]["id"] == "c1"
    assert finished[0]["status"] == "complete"
    assert "light: off" in finished[0]["content"]


def test_the_call_is_announced_before_its_result(tmp_path) -> None:
    """Otherwise the window cannot show "Marvi is checking the room" while it
    runs -- it would only ever learn about the call after it was over."""
    events = list(
        chat(tmp_path, lambda name, arguments: {"status": "ok", "result": "x"}).send_stream("hi")
    )
    kinds = [next(iter(k for k in ("tool_call", "tool_result") if k in e), None) for e in events]
    kinds = [k for k in kinds if k]

    assert kinds == ["tool_call", "tool_result"]


def test_the_reply_keeps_the_whole_trace_in_order(tmp_path) -> None:
    store_chat = chat(tmp_path, lambda name, arguments: {"status": "ok", "result": "light: off"})
    list(store_chat.send_stream("what is the room doing?"))

    reply = next(row for row in reversed(store_chat.store.history()) if row["role"] == "assistant")
    steps = [part["type"] for part in reply["parts"]]

    # Thought, commentary and the call from round one; the closing thought
    # from round two; then the answer.
    assert steps[:5] == ["reasoning", "commentary", "tool", "reasoning", "text"]
    assert reply["parts"][1]["text"] == "Let me check the room."
    assert reply["parts"][2]["name"] == "room_state"


def test_commentary_does_not_leak_into_the_answer(tmp_path) -> None:
    """"Let me check the room." was said on the way, not as the reply."""
    store_chat = chat(tmp_path, lambda name, arguments: {"status": "ok", "result": "x"})
    list(store_chat.send_stream("what is the room doing?"))

    reply = next(row for row in reversed(store_chat.store.history()) if row["role"] == "assistant")

    assert reply["content"] == "The light is off."


def test_how_long_the_work_took_is_stored(tmp_path) -> None:
    store_chat = chat(tmp_path, lambda name, arguments: {"status": "ok", "result": "x"})
    list(store_chat.send_stream("what is the room doing?"))

    reply = next(row for row in reversed(store_chat.store.history()) if row["role"] == "assistant")

    assert isinstance(reply["meta"]["worked_ms"], int)
    assert reply["meta"]["worked_ms"] >= 0


def test_a_failed_call_is_recorded_as_failed(tmp_path) -> None:
    def refuses(name, arguments):
        return {"status": "failed", "error": "the room sensor is offline"}

    events = list(chat(tmp_path, refuses).send_stream("what is the room doing?"))
    finished = [e["tool_result"] for e in events if "tool_result" in e]

    assert finished[0]["status"] == "failed"


def test_a_huge_result_is_trimmed_for_display_only(tmp_path) -> None:
    """The model saw every byte. The stored trace is for a person skimming."""
    page = "x" * (TRACE_RESULT_CHARS * 5)
    events = list(
        chat(tmp_path, lambda name, arguments: {"status": "ok", "result": page}).send_stream("read it")
    )
    finished = [e["tool_result"] for e in events if "tool_result" in e]

    assert len(finished[0]["content"]) <= TRACE_RESULT_CHARS + 1


def test_the_untrusted_data_markers_are_stripped_for_display(tmp_path) -> None:
    """They exist to tell the model the text came from outside; a person
    reading the trace already knows, and the markers are noise to them."""
    events = list(
        chat(tmp_path, lambda name, arguments: {"status": "ok", "result": "light: off"}).send_stream(
            "hi"
        )
    )
    finished = [e["tool_result"] for e in events if "tool_result" in e]

    assert "EXTERNAL DATA" not in finished[0]["content"]
