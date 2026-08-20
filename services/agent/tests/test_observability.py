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
        "metrics_collected",
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


def test_llm_timing_reports_time_to_first_token(session: FakeSession, caplog) -> None:
    """The number that decides whether a spoken turn feels quick."""
    # Named to match, because the dispatch is on the class name -- the same
    # way the SDK's own metric types are told apart.
    class LLMMetrics:
        ttft, duration = 0.412, 1.9
        prompt_tokens, completion_tokens, cancelled = 1200, 40, False

    metric = LLMMetrics()

    with caplog.at_level(logging.INFO, logger="marvi.voice"):
        session.fire("metrics_collected", SimpleNamespace(metrics=metric))

    line = " ".join(r.getMessage() for r in caplog.records)
    assert "412ms" in line
    assert "ttft" in line


def test_tts_timing_reports_time_to_first_byte(session: FakeSession, caplog) -> None:
    class TTSMetrics:
        ttfb, duration, audio_duration, cancelled = 0.25, 1.1, 3.0, False

    metric = TTSMetrics()

    with caplog.at_level(logging.INFO, logger="marvi.voice"):
        session.fire("metrics_collected", SimpleNamespace(metrics=metric))

    assert "250ms" in " ".join(r.getMessage() for r in caplog.records)


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


def test_unknown_metrics_do_not_raise() -> None:
    observability._log_metrics(SimpleNamespace())
    observability._log_metrics(None)


def test_durations_read_in_milliseconds() -> None:
    assert observability._ms(0.412) == "412ms"
    assert observability._ms(None) == "?"
    assert observability._ms("nonsense") == "?"


def test_long_transcripts_are_trimmed() -> None:
    """A log line that wraps five times is one nobody reads to the end of."""
    trimmed = observability._excerpt("x" * 1000)

    assert len(trimmed) <= observability.EXCERPT + 1
    assert trimmed.endswith("…")
