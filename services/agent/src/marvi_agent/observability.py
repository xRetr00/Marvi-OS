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

**Metrics are the useful half.** Each turn carries its own timings — LLM time
to first token, TTS time to first byte, playback, and `e2e_latency`, which is
the only one a person actually feels: from them finishing speaking to hearing a
word back. That is what diagnoses a slow turn and what the latency work needs.

They come off `ChatMessage.metrics` rather than the `metrics_collected` event,
which the SDK deprecates — and which it told us in the log the first time this
ran, this module catching a fault in itself.
"""

from __future__ import annotations

import logging
import time
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

    # When the user stopped talking. The gap between that and Marvi starting
    # to think is dead air nothing else measures: the per-turn metrics begin at
    # the LLM call, so everything spent deciding the turn was over -- the STT
    # waiting out its silence, then endpointing waiting out its own -- was
    # invisible, and it is the part a person actually experiences as a pause.
    stopped: list[float] = []

    @session.on("user_state_changed")
    def _user_state(event: Any) -> None:
        # VAD. "listening -> speaking" is the first sign Marvi hears anything
        # at all; if this never fires, no audio is reaching the session and
        # nothing downstream will happen.
        old = getattr(event, "old_state", "?")
        new = getattr(event, "new_state", "?")
        if old == "speaking":
            stopped[:] = [time.monotonic()]
        log.info("vad: user %s -> %s", old, new)

    @session.on("agent_state_changed")
    def _agent_state(event: Any) -> None:
        # The pipeline stage, in one line: idle -> listening -> thinking ->
        # speaking. Whichever one it stops at is the one that broke.
        new = getattr(event, "new_state", "?")
        if new == "thinking" and stopped:
            log.info(
                "turn: %.0fms from the user stopping to Marvi starting",
                (time.monotonic() - stopped[0]) * 1000,
            )
            stopped.clear()
        log.info("stage: %s -> %s", getattr(event, "old_state", "?"), new)

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
        _log_turn_metrics(role, getattr(item, "metrics", None) or {})

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

    @session.on("session_usage_updated")
    def _usage(event: Any) -> None:
        log.info("usage: %s", getattr(event, "usage", event))


def _log_turn_metrics(role: str, report: Any) -> None:
    """Per-turn timings, from the message they belong to.

    `metrics_collected` was the obvious place for this and the SDK deprecates
    it -- it said so in the log the first time this ran, which is the logging
    catching a fault in itself. Timings ride on the ChatMessage now, so they
    arrive attached to the turn they describe rather than as a loose stream to
    be correlated.
    """
    if not isinstance(report, dict) or not report:
        return

    if role == "user":
        # How long Marvi waits after you stop talking. Too long feels rude;
        # too short cuts you off mid-sentence.
        log.info(
            "turn-taking: transcript %s behind, end of turn %s",
            _ms(report.get("transcription_delay")),
            _ms(report.get("end_of_turn_delay")),
        )
        return

    # The three numbers that decide whether a spoken reply feels quick, and
    # the one that actually matters to a person: e2e, which is everything from
    # them finishing to hearing a word back.
    log.info(
        "reply: llm ttft %s, tts ttfb %s, playback %s, end to end %s",
        _ms(report.get("llm_node_ttft")),
        _ms(report.get("tts_node_ttfb")),
        _ms(report.get("playback_latency")),
        _ms(report.get("e2e_latency")),
    )
    tps = report.get("llm_node_tps")
    if tps:
        log.debug("reply: %.1f tokens/second", tps)
