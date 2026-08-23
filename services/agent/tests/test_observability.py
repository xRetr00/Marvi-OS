"""Pipeline logging.

Tested because it is the thing we reach for when nothing else works, and a
diagnostic that is itself broken is worse than none: it says the stage was
fine when nobody was watching it.

The handlers are exercised against events shaped like the real ones and
against events missing every field, because a log line that raises inside a
conversation would take down the conversation it exists to explain.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from marvi_agent import observability


class FakeSession:
    """Records handlers the way `AgentSession.on` registers them."""

    def __init__(self) -> None:
        self.handlers: dict[str, list] = {}

    def on(self, event: str):
        def register(fn):
            self.handlers.setdefault(event, []).append(fn)
            return fn

        return register

    def fire(self, event: str, payload: object = None) -> None:
        for handler in self.handlers.get(event, []):
            handler(payload)


@pytest.fixture
def session() -> FakeSession:
    fake = FakeSession()
    observability.attach(fake)
    return fake


def test_every_stage_is_wired(session: FakeSession) -> None:
    """The four stages a voice turn passes through, plus the failures.

    Each of these has silently not happened at some point in this project's
    life, and each was indistinguishable from the others while unwired.
    """
    for event in (
        "user_state_changed",  # VAD
        "user_input_transcribed",  # STT
        "agent_state_changed",  # LLM (thinking)
        "speech_created",  # TTS
        "overlapping_speech",  # barge-in
        "agent_false_interruption",
        "function_tools_executed",
        "session_usage_updated",
        "user_transcription_timeout",
        "error",
        "close",
    ):
        assert event in session.handlers, f"{event} is not logged"


def test_speech_becoming_words_is_logged(session: FakeSession, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="marvi.voice"):
        session.fire(
            "user_input_transcribed",
            SimpleNamespace(transcript="turn the kitchen light on", is_final=True),
        )

    assert any("turn the kitchen light on" in r.getMessage() for r in caplog.records)


def test_a_transcript_that_never_arrives_is_a_warning(session: FakeSession, caplog) -> None:
    """Sound that never becomes words is not the same as silence."""
    with caplog.at_level(logging.WARNING, logger="marvi.voice"):
        session.fire("user_transcription_timeout", SimpleNamespace())

    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_a_pipeline_error_is_logged_as_an_error(session: FakeSession, caplog) -> None:
    with caplog.at_level(logging.ERROR, logger="marvi.voice"):
        session.fire("error", SimpleNamespace(error="the TTS engine died"))

    assert any("the TTS engine died" in r.getMessage() for r in caplog.records)


def test_a_malformed_event_does_not_break_the_conversation(session: FakeSession) -> None:
    """Diagnostics must not be able to take down the thing they diagnose.

    Every handler reads attributes off an event it did not construct, and the
    SDK's event shapes change between versions. Raising here would end a call
    over a log line.
    """
    for event in list(session.handlers):
        session.fire(event, SimpleNamespace())
        session.fire(event, None)


def test_a_malformed_metrics_report_does_not_raise() -> None:
    """The report is a TypedDict off a message, so anything can arrive."""
    observability._log_turn_metrics("assistant", None)
    observability._log_turn_metrics("assistant", {})
    observability._log_turn_metrics("user", "not a dict")
    observability._log_turn_metrics("assistant", {"e2e_latency": "nonsense"})


def test_durations_read_in_milliseconds() -> None:
    assert observability._ms(0.412) == "412ms"
    assert observability._ms(None) == "?"
    assert observability._ms("nonsense") == "?"


def test_long_transcripts_are_trimmed() -> None:
    """A log line that wraps five times is one nobody reads to the end of."""
    trimmed = observability._excerpt("x" * 1000)

    assert len(trimmed) <= observability.EXCERPT + 1
    assert trimmed.endswith("…")


def test_a_reply_reports_the_timings_that_matter(session: FakeSession, caplog) -> None:
    """Per-turn metrics, from the message they belong to.

    They used to come from `metrics_collected`, which the SDK deprecates -- and
    which it said in the log the first time this module ran, the logging
    catching a fault in itself.

    `e2e_latency` is the one a person actually feels: from finishing speaking
    to hearing a word back.
    """
    item = SimpleNamespace(
        role="assistant",
        text_content="the light is on",
        metrics={
            "llm_node_ttft": 0.412,
            "tts_node_ttfb": 0.25,
            "playback_latency": 0.08,
            "e2e_latency": 0.95,
        },
    )

    with caplog.at_level(logging.INFO, logger="marvi.voice"):
        session.fire("conversation_item_added", SimpleNamespace(item=item))

    line = " ".join(r.getMessage() for r in caplog.records)
    assert "412ms" in line
    assert "250ms" in line
    assert "950ms" in line, "end-to-end latency is the number a person feels"


def test_a_user_turn_reports_how_long_marvi_waited(session: FakeSession, caplog) -> None:
    item = SimpleNamespace(
        role="user",
        text_content="turn the light on",
        metrics={"transcription_delay": 0.12, "end_of_turn_delay": 0.48},
    )

    with caplog.at_level(logging.INFO, logger="marvi.voice"):
        session.fire("conversation_item_added", SimpleNamespace(item=item))

    assert "480ms" in " ".join(r.getMessage() for r in caplog.records)


def test_a_turn_without_metrics_is_still_logged(session: FakeSession, caplog) -> None:
    """Metrics are optional on the message; the transcript is not."""
    item = SimpleNamespace(role="assistant", text_content="hello", metrics=None)

    with caplog.at_level(logging.INFO, logger="marvi.voice"):
        session.fire("conversation_item_added", SimpleNamespace(item=item))

    assert any("hello" in r.getMessage() for r in caplog.records)


def test_the_deprecated_metrics_event_is_not_used() -> None:
    """It warns on every session and is going away."""
    import inspect

    assert "metrics_collected" not in inspect.getsource(observability.attach)


def test_voice_usage_reports_only_the_increment(monkeypatch) -> None:
    reports: list[dict] = []

    class Reply:
        pass

    monkeypatch.setattr("httpx.post", lambda _url, json, timeout: reports.append(json) or Reply())
    previous = observability._report_usage(
        "openai", {"llm_prompt_tokens": 100, "llm_completion_tokens": 20}, {}
    )
    observability._report_usage(
        "openai", {"llm_prompt_tokens": 160, "llm_completion_tokens": 35}, previous
    )

    assert reports[0]["input"] == 100
    assert reports[1]["input"] == 60
    assert reports[1]["output"] == 15
