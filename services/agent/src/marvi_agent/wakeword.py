"""Wake word: Marvi hears everything, and answers to her name.

An always-on assistant has a problem an on-demand one does not. The microphone
is live in the room the whole time, so without a gate every remark in the room
is a turn, every turn is an LLM call, and Marvi talks over conversations that
were never addressed to her.

The gate is a small ONNX classifier trained on the phrase itself
(``wakeword/marvi.onnx``, trained with LiveKit's ``livekit-wakeword``). It runs
locally on the audio already arriving in the room -- no extra capture, no audio
leaving the machine, and nothing sent to a provider until she is spoken to.

**Where this runs, and why here.** LiveKit's own example runs the detector on
the client, which then connects to a room; that fits a device that is idle most
of the day. Marvi is already in the room continuously, so the audio is already
here, and putting the detector next to it means no second capture path and no
ONNX runtime in the renderer. What the gate controls is therefore not whether
audio is captured but whether the *session* listens to it: everything upstream
of ``session.input`` runs regardless, and the STT, the LLM and the reply do not.

The model is the retrained one. The first attempt scored ~0.79 on an empty
room -- the same band as a real "marvi" -- which is another way of saying it had
learned nothing. This one scores 0.0 on silence.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from livekit import rtc

if TYPE_CHECKING:
    from livekit.agents import AgentSession

log = logging.getLogger("marvi.wakeword")

#: How long to wait for the Gateway to take a detection. Short: this runs on
#: the audio path, and a slow acknowledgement must not delay Marvi answering.
REPORT_TIMEOUT = 1.5


def _gateway_settings() -> dict:
    """What the UI has been told, asked of the one process that knows.

    Empty when the Gateway cannot be reached, so the environment decides and
    Marvi still starts. A wake word that fails closed on a network blip would
    leave her permanently deaf.
    """
    import contextlib
    import os as _os

    with contextlib.suppress(Exception):
        import httpx

        base = _os.environ.get("MARVI_GATEWAY_URL", "http://127.0.0.1:8765").rstrip("/")
        body = httpx.get(f"{base}/voice/wake", timeout=REPORT_TIMEOUT).json()
        if isinstance(body, dict):
            return body
    return {}


def _report_heard(confidence: float) -> None:
    """Tell the Gateway the wake word fired. Never raises.

    Fire and forget. A detection that could not be reported is still a
    detection, and Marvi listening matters more than the UI knowing about it.
    """
    import contextlib
    import os

    with contextlib.suppress(Exception):
        import httpx

        base = os.environ.get("MARVI_GATEWAY_URL", "http://127.0.0.1:8765").rstrip("/")
        httpx.post(
            f"{base}/voice/wake/heard",
            json={"confidence": confidence},
            timeout=REPORT_TIMEOUT,
        )

#: Ships in the repo rather than being downloaded: it is 97 KB, it is the thing
#: that decides whether Marvi answers at all, and an assistant that cannot hear
#: her own name until a download finishes is not an assistant yet.
DEFAULT_MODEL = Path(__file__).resolve().parents[2] / "wakeword" / "marvi.onnx"

#: The classifier wants 16 kHz mono; the room carries 48 kHz. `AudioStream`
#: resamples on the way out, so this is the only place the rate is stated.
SAMPLE_RATE = 16_000

#: The model is stateless and scores a whole window at a time. Its own
#: docstring: "pass a complete audio window each time. ~2 seconds of 16 kHz
#: audio is recommended (yields exactly 16 embeddings for the classifier).
#: Shorter chunks that lack enough data return zero scores."
#:
#: This was the bug. Frames arriving from the room are about 10 ms, and each
#: was handed to `predict` on its own -- far short of the 16 embeddings the
#: classifier needs, so every call returned exactly 0.0 and the wake word could
#: never fire. It looked like a model correctly ignoring noise.
WINDOW_SAMPLES = SAMPLE_RATE * 2

#: How far the window slides between scores. Matches the reference listener's
#: 80 ms frame: often enough to catch a word wherever it falls, rare enough
#: that the ONNX run is not the agent's main occupation.
HOP_SAMPLES = SAMPLE_RATE // 1000 * 80

#: Minimum gap between detections, so one utterance is one wake. The window
#: slides in 80 ms steps and a spoken "Marvi" stays inside it for over a
#: second, which without this would score again on every hop.
DEBOUNCE_SECONDS = 2.0

#: Scores above this count as her name. Deliberately not lower: the cost of a
#: false wake is Marvi interrupting a conversation she was not part of, which
#: is worse than having to say her name twice.
DEFAULT_THRESHOLD = 0.5

#: Retained only so an old setting does not become an error. The window is
#: gone: a wake word starts a conversation and the conversation ends when it is
#: over, not on a timer. Marvi cutting someone off mid-thought because thirty
#: seconds elapsed is not how a conversation works.
DEFAULT_WINDOW_SECONDS = 30.0


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        log.warning("ignoring bad %s; using %s", name, default)
        return default


class WakeGate:
    """Keeps a session deaf until the wake word arrives.

    Not a filter on the audio -- the session's own input switch, flipped from
    outside. That matters for interruption: once she is awake the normal turn
    handling is entirely untouched, so barge-in, endpointing and everything else
    behave exactly as they do without a wake word.
    """

    def __init__(
        self,
        model_path: Path = DEFAULT_MODEL,
        threshold: float = DEFAULT_THRESHOLD,
        window: float = DEFAULT_WINDOW_SECONDS,
    ) -> None:
        from livekit.wakeword import WakeWordModel

        self.threshold = threshold
        self.window = window
        self._model = WakeWordModel(models=[str(model_path)])
        self._awake = False
        self._session: AgentSession | None = None
        self._tasks: set[asyncio.Task] = set()

    @classmethod
    def from_env(cls) -> WakeGate | None:
        """The configured gate, or None when Marvi should just listen.

        Settings come from the Gateway, with the environment as the fallback.
        That is not a preference -- it is the only way the switch in the UI can
        reach here at all. The Agent is a separate process whose environment is
        fixed when the desktop spawns it, so turning the wake word off in
        Settings changed a file this process never reads. It armed anyway,
        muted the session's audio input, and the microphone went to a session
        that was not listening: VAD saw nothing, went `away`, and no transcript
        was ever produced. It looked exactly like broken speech recognition.
        """
        settings = _gateway_settings()

        enabled = settings.get("enabled")
        if enabled is None:
            enabled = _flag("MARVI_WAKE_WORD", True)
        if not enabled:
            log.info("wake word off; Marvi answers from the moment she joins")
            return None

        path = Path(str(settings.get("model") or "") or os.environ.get("MARVI_WAKE_MODEL", "") or DEFAULT_MODEL)
        if not path.is_file():
            # A missing model must not make her deaf. Falling back to always-on
            # is the safe direction to fail: too talkative beats unreachable.
            log.warning("no wake word model at %s; Marvi answers every turn", path)
            return None

        try:
            threshold = settings.get("threshold")
            return cls(
                model_path=path,
                threshold=float(threshold)
                if threshold is not None
                else _number("MARVI_WAKE_THRESHOLD", DEFAULT_THRESHOLD),
                window=_number("MARVI_WAKE_WINDOW", DEFAULT_WINDOW_SECONDS),
            )
        except Exception as exc:  # pragma: no cover - depends on the runtime
            log.warning("could not load the wake word model: %s", exc)
            return None

    # -- state ---------------------------------------------------------------

    @property
    def awake(self) -> bool:
        """In a conversation.

        A latch, not a timer. It used to be `now < deadline`, so being spoken
        to had to keep pushing a deadline back and any gap longer than the
        window silently closed the session mid-conversation.
        """
        return self._awake

    def _listen(self, *, reason: str, confidence: float = 0.0) -> None:
        """Open the conversation. Idempotent."""
        if self.awake:
            return
        self._awake = True
        log.info("wake word: conversation open (%s)", reason)
        if self._session is not None:
            self._session.input.set_audio_enabled(True)
        # Told to the Gateway so the UI can acknowledge it. Without this a gate
        # that silently is not running looks exactly like one that is running
        # and never triggers -- both are Marvi ignoring you.
        _report_heard(confidence)

    def close(self) -> None:
        """End the conversation and listen for her name again.

        Called by the `end_conversation` tool, so the model decides when a
        conversation is over from what was said rather than from a timer or a
        list of stop-words.
        """
        if not self._awake:
            return
        self._awake = False
        if self._session is not None:
            self._session.input.set_audio_enabled(False)
        log.info("wake word: conversation closed; listening for her name")


    # -- running -------------------------------------------------------------

    def attach(self, session: AgentSession, room: rtc.Room) -> None:
        """Start gating `session` on the audio arriving in `room`.

        Nothing here touches the FFI. The room may still be completing its
        connect handshake when this runs -- `session.start` kicks the connect
        off as a concurrent task and returns before it finishes -- so opening
        an audio stream on it now would be reaching into a room that is not
        ready. Every stream is opened from `track_subscribed`, which by
        definition fires after it is.
        """
        self._session = session
        session.input.set_audio_enabled(False)
        # No window in the message: there is no window any more. It said
        # "window 30s" while the conversation stayed open until closed, which
        # is a log line describing code that was deleted.
        log.info("wake word armed (threshold %.2f)", self.threshold)

        @room.on("track_subscribed")
        def _on_track(track: rtc.Track, *_args: object) -> None:
            self._watch(track)


    def _watch(self, track: rtc.Track) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            self._spawn(self._consume(track))

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        # Held, because asyncio only keeps a weak reference and a garbage
        # collected task stops silently -- which here means she stops listening
        # with no error anywhere.
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _consume(self, track: rtc.Track) -> None:
        stream = rtc.AudioStream.from_track(
            track=track, sample_rate=SAMPLE_RATE, num_channels=1
        )
        # A rolling two seconds, scored every 80 ms. Both numbers come from the
        # model: it is stateless, so it needs the whole window each time.
        window = np.zeros(0, dtype=np.int16)
        since_last_score = 0
        last_fired = 0.0
        try:
            async for event in stream:
                if self.awake:
                    # No point scoring what she is already listening to, and
                    # this is the common case once a conversation starts. The
                    # window is dropped so a fresh one is built on waking --
                    # otherwise the first score after sleeping would be against
                    # two seconds of her own reply.
                    window = np.zeros(0, dtype=np.int16)
                    since_last_score = 0
                    continue

                samples = np.frombuffer(event.frame.data, dtype=np.int16)
                if not samples.size:
                    continue
                window = np.concatenate((window, samples))[-WINDOW_SAMPLES:]
                since_last_score += samples.size
                if window.size < WINDOW_SAMPLES or since_last_score < HOP_SAMPLES:
                    continue
                since_last_score = 0

                if time.monotonic() - last_fired < DEBOUNCE_SECONDS:
                    continue

                # Off the event loop: the ONNX run is CPU-bound, and blocking
                # here would stall the audio the session is trying to hear.
                scores = await asyncio.to_thread(self._model.predict, window)
                best = max(scores.values(), default=0.0)
                if best >= self.threshold:
                    last_fired = time.monotonic()
                    self._listen(reason=f"heard her name ({best:.2f})", confidence=best)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - depends on the runtime
            # Failing open: a detector that crashes must not leave her deaf.
            log.warning("wake word listener stopped (%s); listening always", exc)
            self._listen(reason="detector failed")
        finally:
            with contextlib.suppress(Exception):
                await stream.aclose()

