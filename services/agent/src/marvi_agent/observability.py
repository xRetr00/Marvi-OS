"""What the voice pipeline is doing, said out loud.

Every fault in this pipeline so far has been diagnosed by reading LiveKit's
own logs and inferring what Marvi was doing between them. A missing speech
engine, a turn dropped by a gate, a session that never started — all three
looked identical from outside, which is to say they looked like nothing.

So this attaches to every stage and reports it. The point is not that any one
line is interesting; it is that when something stops working, the last line
printed says which stage it stopped at.

**Four things, and where each shows up**

* **VAD** — did Marvi hear sound at all? `user_state_changed` goes
  speaking/listening/away.
* **STT** — did that sound become words? `user_input_transcribed`, and
  `user_transcription_timeout` when it did not.
* **LLM** — did the words reach a model and come back? `agent_state_changed`
  passes through `thinking`, and the metrics carry time to first token.
* **TTS** — did the answer become audio? `speech_created`, and the metrics
  carry time to first byte.

Between them: barge-in (`overlapping_speech`), a barge-in that turned out to be
nothing (`agent_false_interruption`), and tool calls.

**Metrics are the useful half.** `metrics_collected` carries per-component
timings — LLM `ttft`, TTS `ttfb`, the end-of-utterance delays that decide how
long a pause feels — which is both what diagnoses a slow turn and what the
latency work needs. They are logged at INFO because a voice turn is not a hot
loop; there are a handful of these per exchange, not thousands.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from livekit.agents.voice import AgentSession

log = logging.getLogger("marvi.voice")

#: Transcripts and replies can be long, and a log line that wraps five times is
#: a log line nobody reads to the end of.
EXCERPT = 200


def _excerpt(text: object) -> str:
    value = str(text or "").strip().replace("\n", " ")
    return value[:EXCERPT] + ("…" if len(value) > EXCERPT else "")


def _ms(seconds: object) -> str:
    """Durations in milliseconds, because that is the unit of a voice turn."""
    try:
        return f"{float(seconds) * 1000:.0f}ms"
    except (TypeError, ValueError):
        return "?"


def attach(session: AgentSession) -> None:
    """Wire every pipeline stage to the log. Never raises.

    Handlers are deliberately defensive: this is diagnostics, and a bad
    attribute access in a log line must not take down a conversation. The whole
    reason it exists is that the conversation was already failing silently.
    """

    @session.on("user_state_changed")
    def _user_state(event: Any) -> None:
        # VAD. "listening -> speaking" is the first sign Marvi hears anything
        # at all; if this never fires, no audio is reaching the session and
        # nothing downstream will happen.
        log.info("vad: user %s -> %s", getattr(event, "old_state", "?"), getattr(event, "new_state", "?"))

    @session.on("agent_state_changed")
    def _agent_state(event: Any) -> None:
        # The pipeline stage, in one line: idle -> listening -> thinking ->
        # speaking. Whichever one it stops at is the one that broke.
        log.info(
            "stage: %s -> %s", getattr(event, "old_state", "?"), getattr(event, "new_state", "?")
        )

    @session.on("user_input_transcribed")
    def _transcribed(event: Any) -> None:
        final = getattr(event, "is_final", True)
        log.info(
            "stt%s: %s", "" if final else " (partial)", _excerpt(getattr(event, "transcript", ""))
        )

    @session.on("user_transcription_timeout")
    def _stt_timeout(_event: Any) -> None:
        # Sound arrived and never became words. Distinct from silence, and the
        # two are indistinguishable without this.
        log.warning("stt: timed out waiting for a transcript")

    @session.on("speech_created")
    def _speech(event: Any) -> None:
        log.info("tts: speaking (%s)", getattr(event, "source", "?"))

    @session.on("conversation_item_added")
    def _item(event: Any) -> None:
        item = getattr(event, "item", None)
        role = getattr(item, "role", "?")
        log.info("turn: %s said %s", role, _excerpt(getattr(item, "text_content", "")))

    @session.on("function_tools_executed")
    def _tools(event: Any) -> None:
        calls = getattr(event, "function_calls", []) or []
        log.info("tools: %s", ", ".join(getattr(c, "name", "?") for c in calls) or "(none)")

    @session.on("overlapping_speech")
    def _bargein(_event: Any) -> None:
        log.info("barge-in: the user spoke over Marvi")

    @session.on("agent_false_interruption")
    def _false_bargein(_event: Any) -> None:
        # Marvi stopped, then found nothing was said. Worth its own line: too
        # many of these means the interruption threshold is wrong, and it is
        # otherwise invisible.
        log.info("barge-in: false alarm, resuming")

    @session.on("error")
    def _error(event: Any) -> None:
        log.error("pipeline error: %s", getattr(event, "error", event))

    @session.on("close")
    def _close(event: Any) -> None:
        log.info("session closed (%s)", getattr(event, "reason", "?"))

    @session.on("metrics_collected")
    def _metrics(event: Any) -> None:
        _log_metrics(getattr(event, "metrics", None))


def _log_metrics(metric: Any) -> None:
    """One line per component, in the terms that component is judged on."""
    if metric is None:
        return
    kind = type(metric).__name__

    if kind == "LLMMetrics":
        # Time to first token is the number for voice: a turn starts speaking
        # when the first token arrives, and total duration barely shows.
        log.info(
            "llm: ttft %s, total %s, %s prompt + %s completion tokens%s",
            _ms(getattr(metric, "ttft", None)),
            _ms(getattr(metric, "duration", None)),
            getattr(metric, "prompt_tokens", "?"),
            getattr(metric, "completion_tokens", "?"),
            " (cancelled)" if getattr(metric, "cancelled", False) else "",
        )
    elif kind == "TTSMetrics":
        log.info(
            "tts: ttfb %s, generated %s of audio in %s%s",
            _ms(getattr(metric, "ttfb", None)),
            _ms(getattr(metric, "audio_duration", None)),
            _ms(getattr(metric, "duration", None)),
            " (cancelled)" if getattr(metric, "cancelled", False) else "",
        )
    elif kind == "STTMetrics":
        log.info(
            "stt: %s of audio transcribed in %s",
            _ms(getattr(metric, "audio_duration", None)),
            _ms(getattr(metric, "duration", None)),
        )
    elif kind == "EOUMetrics":
        # How long Marvi waits after you stop talking. Too long feels rude;
        # too short cuts you off mid-sentence.
        log.info(
            "turn-taking: end of utterance %s, transcript %s behind",
            _ms(getattr(metric, "end_of_utterance_delay", None)),
            _ms(getattr(metric, "transcription_delay", None)),
        )
    elif kind == "VADMetrics":
        # Idle time only; the per-frame inference count would drown everything.
        log.debug("vad: idle %s", _ms(getattr(metric, "idle_time", None)))
    elif kind == "InterruptionMetrics":
        log.info(
            "barge-in: %s interruptions, %s backchannels, detected in %s",
            getattr(metric, "num_interruptions", "?"),
            getattr(metric, "num_backchannels", "?"),
            _ms(getattr(metric, "detection_delay", None)),
        )
    else:
        log.debug("metrics: %s", metric)
