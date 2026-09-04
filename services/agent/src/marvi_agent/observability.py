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

import contextlib
import logging
import os
import time
from typing import TYPE_CHECKING, Any

from . import troubles

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


def _number(value: Any, *names: str) -> int:
    for name in names:
        raw = value.get(name) if isinstance(value, dict) else getattr(value, name, None)
        if raw is not None:
            with contextlib.suppress(TypeError, ValueError):
                return max(0, int(raw))
    return 0


def _llm_entries(usage: Any) -> list[Any]:
    """The LLM rows of a session usage event, in the shape 1.6 sends.

    `AgentSessionUsage` is `model_usage: list[ModelUsage]` -- one row per
    provider and model, tagged by `type`. This module read a flat object with
    `llm_prompt_tokens` on it, which is the shape from before that change, so
    every field came back `None`, every delta was zero, and the Voice page has
    said `TOKENS 0` through every conversation since.
    """
    rows = getattr(usage, "model_usage", None)
    if rows is None and isinstance(usage, dict):
        rows = usage.get("model_usage")
    return [row for row in (rows or []) if str(getattr(row, "type", "")) == "llm_usage"]


def _report_usage(
    provider: str, usage: Any, previous: dict[str, int], model: str = ""
) -> dict[str, int]:
    """Send only the delta from LiveKit's cumulative session usage event.

    `model` goes with it. The voice worker calls the provider directly rather
    than through the Gateway, so these counters are the *only* record of what
    voice spent -- and without a model name the ledger could say how many
    tokens went out but never which model answered.
    """
    rows = _llm_entries(usage)
    if rows:

        def total(*names: str) -> int:
            return sum(_number(row, *names) for row in rows)

        current = {
            "input": total("input_tokens"),
            "output": total("output_tokens"),
            "cached_input": total("input_cached_tokens"),
            # Not reported per model in this shape; kept so the delta keys and
            # the Gateway's fields stay the same either way.
            "reasoning": 0,
        }
    else:
        current = {
            "input": _number(usage, "llm_prompt_tokens", "input_tokens", "prompt_tokens"),
            "output": _number(usage, "llm_completion_tokens", "output_tokens", "completion_tokens"),
            "cached_input": _number(usage, "llm_cached_prompt_tokens", "cached_input_tokens"),
            "reasoning": _number(usage, "llm_reasoning_tokens", "reasoning_tokens"),
        }
    delta = {name: max(0, value - previous.get(name, 0)) for name, value in current.items()}
    if provider and any(delta.values()):
        with contextlib.suppress(Exception):
            import httpx

            base = os.environ.get("MARVI_GATEWAY_URL", "http://127.0.0.1:8765").rstrip("/")
            httpx.post(
                f"{base}/usage",
                json={"provider": provider, "model": model, **delta},
                timeout=2.0,
            )
    return current


def attach(session: AgentSession, provider: str = "", model: str = "") -> None:
    last_usage: dict[str, int] = {}
    #: Per session, so a fault explained in one conversation is explained
    #: again in the next; the person there may be a different person.
    narrator = troubles.Narrator()
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
        #
        # Said out loud as well as logged. Going quiet is the worst of the
        # three things that can happen here: a wrong transcript can be
        # corrected and a refusal can be argued with, but silence is
        # indistinguishable from Marvi not listening, so the person repeats
        # themselves into nothing and eventually stops asking.
        log.warning("stt: timed out waiting for a transcript")
        with contextlib.suppress(Exception):
            from .session import MISHEARD

            session.say(MISHEARD)

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
        fault = getattr(event, "error", event)
        log.error("pipeline error: %s", fault)
        # And out loud, when it is a fault a person can act on.
        #
        # This was logged and nothing else, so a rate-limited model, an
        # unreachable Gateway and a recogniser that heard nothing were all the
        # same thing from the outside: a pause, then nothing. See `troubles`,
        # including why the line is written there and never taken from the
        # error text.
        with contextlib.suppress(Exception):
            if line := narrator.speak_about(fault):
                log.info("saying what went wrong: %s", line)
                session.say(line)

    @session.on("close")
    def _close(event: Any) -> None:
        log.info("session closed (%s)", getattr(event, "reason", "?"))

    @session.on("session_usage_updated")
    def _usage(event: Any) -> None:
        nonlocal last_usage
        usage = getattr(event, "usage", event)
        # Only when there is something in it. This fired 654 times in one
        # evening with an empty list every time, and those lines are most of
        # what is in the log around a conversation.
        if _llm_entries(usage):
            log.info("usage: %s", usage)
        last_usage = _report_usage(provider, usage, last_usage, model)


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
    _record_turn(report)


def _record_turn(report: dict[str, Any]) -> None:
    """Send the turn's end-to-end timing where it can be aggregated.

    These numbers already existed, and only in the log. The Gateway records
    the LLM leg and can report a median and a p95 for it; the number a person
    actually feels -- them finishing to hearing a word back -- was written to
    a line of text and never counted. Answering "is Marvi fast right now"
    meant a regex over `agent.log`, which is how the p90 went unnoticed at
    5.5 seconds while the median sat at 1.8.

    Posted under its own path so it aggregates beside the LLM leg rather than
    mixing with it. Never raises: this is diagnostics, and the conversation
    does not stop for it.
    """
    e2e = report.get("e2e_latency")
    if not e2e:
        return
    with contextlib.suppress(Exception):
        import httpx

        base = os.environ.get("MARVI_GATEWAY_URL", "http://127.0.0.1:8765").rstrip("/")
        httpx.post(
            f"{base}/latency",
            json={
                "surface": "voice",
                "path": "turn",
                # `first_token_ms` is the summary's "how long until something
                # happened" slot, and for a spoken turn that is the first word
                # heard, not the first token generated.
                "first_token_ms": float(e2e) * 1000.0,
                "total_ms": float(report.get("llm_node_ttft") or 0.0) * 1000.0,
                # What was actually said, so the behaviour suites can be run
                # against real turns instead of scripted ones. Prompt leaks,
                # monologues and invented memories are all visible here and
                # were every one of them found by reading logs by hand.
                "said": str(report.get("said") or "")[:400],
                "heard": str(report.get("heard") or "")[:400],
            },
            timeout=2.0,
        )
