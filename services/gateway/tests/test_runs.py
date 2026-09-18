"""One turn as a list of what it did, and running it again without doing it."""

from __future__ import annotations

import pytest

from marvi_gateway import observations, runs
from marvi_gateway.chat import Chat, ChatStore


@pytest.fixture(autouse=True)
def recording(monkeypatch, tmp_path):
    monkeypatch.setenv("MARVI_OBSERVATIONS", str(tmp_path / "observations.jsonl"))
    yield


def _recorded(trace: str = "t1") -> str:
    runs.step(trace, "asked", surface="chat", text="what is the weather?")
    runs.step(trace, "tool", name="get_weather", args='{"city": "Cairo"}', result="32C and clear")
    runs.step(trace, "answered", tokens=120, error="")
    return trace


def test_a_turn_reads_back_in_order() -> None:
    steps = runs.journal(_recorded())

    assert [row["event"] for row in steps] == ["asked", "tool", "answered"]
    assert steps[1]["name"] == "get_weather"


def test_the_recent_turns_summarise_themselves() -> None:
    _recorded("t1")
    _recorded("t2")

    listed = runs.traces()

    assert {row["trace"] for row in listed} == {"t1", "t2"}
    first = next(row for row in listed if row["trace"] == "t1")
    assert first["tools"] == ["get_weather"] and first["tokens"] == 120
    assert first["asked"].startswith("what is the weather")


def test_a_replay_answers_tools_from_the_recording_and_runs_none() -> None:
    """The whole safety of this: a replay cannot act."""
    _recorded()
    seen: list[list[dict]] = []

    class Model:
        def __init__(self) -> None:
            self.calls = 0

        def call_with_fallback(self, messages, **_kwargs):
            seen.append(list(messages))
            self.calls += 1

            class Answer:
                # First round asks for the tool; second answers.
                tool_calls = (
                    [{"name": "get_weather", "arguments": '{"city": "Cairo"}'}]
                    if self.calls == 1
                    else []
                )
                text = "" if self.calls == 1 else "It is 32C and clear in Cairo."

            return Answer()

    answer = runs.replay(Model(), "t1", model="another-model")

    assert answer["now"]["tools"] == ["get_weather"]
    assert answer["same_tools"] is True
    assert "32C" in answer["now"]["answer"]
    assert answer["executed"].startswith("nothing")
    # The recorded result was handed to the model rather than the tool run.
    assert any("[replay] get_weather answered: 32C and clear" in str(row) for row in seen[-1])


def test_a_tool_the_recording_never_called_is_said_rather_than_run() -> None:
    _recorded()

    class Inventive:
        def call_with_fallback(self, messages, **_kwargs):
            asked = any("[replay]" in str(row.get("content")) for row in messages)

            class Answer:
                tool_calls = [] if asked else [{"name": "send_email", "arguments": "{}"}]
                text = "I would have emailed them." if asked else ""

            return Answer()

    answer = runs.replay(Inventive(), "t1")

    assert answer["now"]["tools"] == ["send_email"]
    assert answer["same_tools"] is False
    assert answer["executed"].startswith("nothing")


def test_an_unknown_run_is_an_error_not_an_empty_replay() -> None:
    assert "no run called" in runs.replay(object(), "nope")["error"]


def test_a_real_turn_records_its_steps(tmp_path, monkeypatch) -> None:
    """End to end: the turn writes the journal that the replay reads."""
    monkeypatch.setenv("MARVI_OBSERVATIONS", str(tmp_path / "observations.jsonl"))
    store = ChatStore(tmp_path / "chat.db")
    thread = store.create_thread("A turn")["id"]

    list(Chat(store=store).send_stream("hello there", thread_id=thread))

    rows = observations.read("run", limit=50)
    kinds = {row["event"] for row in rows}
    assert {"asked", "answered"} <= kinds
    asked = next(row for row in rows if row["event"] == "asked")
    assert asked["text"] == "hello there" and asked["surface"] == "chat"
    # Every step of one turn shares one id.
    assert len({row["trace"] for row in rows}) == 1
