"""Kyutai STT 1B, with the semantic VAD that is the reason to have it.

The third recogniser Marvi can be told to use, and the only one that says when
the person has finished talking rather than leaving that to a timer.

## Why this model at all

Measured on this machine, it loses on both of the numbers a bakeoff usually
decides on. Over 162 EdAcc clips: 35.26% word error against Parakeet's 20.81%,
and 63.8 ms of work per 80 ms frame -- realtime with about a fifth of the
budget spare, where Parakeet uses a twentieth. On the Arabic slice, 20.17%
against 8.03%. It is not the accurate one and it is not the fast one.

What it has instead is four extra prediction heads trained alongside the text,
each answering "has the speaker paused for N seconds" for N of 0.5, 1.0, 2.0
and 3.0 -- and answering it from content and intonation, not from silence. A
sentence that sounds finished scores high before the silence arrives. A
sentence that trails off mid-thought does not, however long the gap.

Every other recogniser here is followed by a fixed timer: 600 ms of quiet and
the turn is over. That timer is wrong in both directions at once. It cuts off
someone thinking mid-sentence, and it makes everyone else wait 600 ms after an
obviously complete question. This model is the only one that can do better,
which is why it is worth carrying a recogniser that is beaten on paper.

## The checkpoint

`kyutai/stt-1b-en_fr-candle`, not `kyutai/stt-1b-en_fr`. The two publish the
same model under names that suggest a Rust build and a PyTorch build, and the
difference is not the format:

    stt-1b-en_fr          131 tensors, no extra_heads, config has no heads
    stt-1b-en_fr-candle   135 tensors, extra_heads.0..3.weight [6, 2048]

The plain repo has no VAD weights at all. Marvi's first benchmark used it and
so measured a model with the interesting part missing. The `-candle` suffix
names the implementation it was published for, not a format only Rust reads:
the config is `moshi`'s own, and `LMGen` builds the heads from
`extra_heads_num_heads`.

## Reading the heads

`LMGen.step` returns `out[0]` and discards the rest. `step_with_extra_heads`
returns `(tokens, heads)` where each head is a softmax over six values, and
the pause probability is element 0. Kyutai's own Rust example thresholds
`prs[2][0] > 0.5`, and Unmute -- their voice agent -- uses index 2 as well.
Lower indices predict more aggressively.

## What is guarded, and why

Their issue tracker records the failure mode: the pause heads spike on digit
sequences and on audio the model reads as silence, sometimes past 0.99. A bare
threshold would end the turn in the middle of somebody reading out a phone
number. Two guards, both cheap:

* nothing has been transcribed yet -> ignore the VAD entirely. An end-of-turn
  before the first word is not a turn ending.
* the timer stays as a ceiling. If the VAD never fires, the turn still ends
  exactly when it does today, so the worst case is the behaviour of every
  other recogniser here.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
from livekit.agents import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions, stt
from livekit.agents.types import NOT_GIVEN, NotGivenOr

from . import sidecars
from .parakeet_stt import APP_DATA

log = logging.getLogger("marvi.voice")

MODEL_ROOT = APP_DATA / "models/stt/kyutai-stt-1b-candle"

#: The isolated project the recogniser runs in, and its entry point.
PROJECT = "services/stt-kyutai"
MODULE = "marvi_stt_kyutai.host"

#: The files the checkpoint is made of. Named rather than globbed so a partial
#: download reads as missing instead of loading and failing deep inside moshi.
WEIGHTS = "model.safetensors"
MIMI = "mimi-pytorch-e351c8d8@125.safetensors"
TOKENIZER = "tokenizer_en_fr_audio_8000.model"
CONFIG = "config.json"

#: Which pause head to believe. 0 is 0.5 s, 1 is 1.0 s, 2 is 2.0 s, 3 is 3.0 s,
#: and lower is more eager. Two is what Kyutai ship in Unmute.
VAD_INDEX_SETTING = "MARVI_KYUTAI_VAD_INDEX"
VAD_INDEX = 2

#: Kyutai's own Rust example compares against 0.5.
VAD_THRESHOLD_SETTING = "MARVI_KYUTAI_VAD_THRESHOLD"
VAD_THRESHOLD = 0.5

#: Consecutive frames over the threshold before the turn is called ended.
#:
#: The heads spike for a frame or two mid-utterance -- on a breath, on a digit
#: sequence -- and a bare threshold acts on every one of them. Measured over 14
#: voice-agent clips, counting crossings before the real end of the turn:
#:
#:     hold   head 1 (1.0s)        head 2 (2.0s)
#:     1      8 early, -0.44s      5 early, -0.44s
#:     3      2 early, -0.28s      1 early, -0.28s
#:     5      1 early, -0.12s      1 early, -0.12s
#:
#: Three frames is 240 ms and takes head 2 from five premature endings to one
#: while giving up 0.16 s. Five buys nothing more and costs another 0.16 s.
VAD_HOLD_SETTING = "MARVI_KYUTAI_VAD_HOLD"
VAD_HOLD = 3

#: Mimi's rate, which is not Marvi's.
#:
#: Every other recogniser here takes 16 kHz, so `SAMPLE_RATE` is 16,000 and the
#: frame size was computed from it -- 1,280 samples, which the sidecar refused
#: as "expected 1920, got 1280". Mimi runs at 24 kHz and consumes exactly 1,920
#: samples per step; nothing else is a valid feed size.
#:
#: Declared to `RecognizeStream` so LiveKit resamples the room's audio on the
#: way in, rather than this doing it by hand on every frame.
KYUTAI_SAMPLE_RATE = 24_000

#: Mimi's frame. The model consumes exactly this much audio per step and
#: nothing else is a valid feed size.
FRAME_SECONDS = 0.08
FRAME_SAMPLES = int(FRAME_SECONDS * KYUTAI_SAMPLE_RATE)

#: Silence the model is given before the first real audio.
#:
#: Not a nicety. Fed audio that begins with a word already in progress, this
#: model emits nothing at all -- measured on six clips that returned empty
#: transcripts in the first benchmark, all six of which transcribed correctly
#: with a second of silence in front. The checkpoint's own
#: `audio_silence_prefix_seconds` is 0.0, which is what made it easy to miss.
#:
#: Live, the microphone supplies this for free: the stream is open and quiet
#: before anyone speaks. It is here for the case where it is not -- a stream
#: that opens on a word.
PREFIX_SECONDS = 1.0

#: How long an open stream may hear nothing before it is reset anyway.
#:
#: The fallback timer only fires when something has been transcribed:
#:
#:     elif self._said and time.monotonic() - self._spoke_at >= self._SILENCE
#:
#: which is right for ending a turn -- silence that never became words is not a
#: turn -- and wrong for the model, because `_settle` is also the only thing
#: that resets it. An utterance that produced no text at all left the stream
#: open, holding whatever state it had, and the next one carried on inside it.
#:
#: Live, that came in pairs: a stretch of audio transcribed to nothing, Marvi
#: apologised, the person repeated themselves, and *that* transcribed to
#: nothing too:
#:
#:     15:05:19,891  vad: user listening -> speaking
#:     15:05:26,294  vad: user speaking -> listening     <- 6.4s, no partials
#:     15:05:27,719  stt: timed out waiting for a transcript
#:     15:05:29,874  turn: assistant said Sorry, I did not catch that.
#:     15:05:31,240  vad: user listening -> speaking
#:     15:05:34,139  vad: user speaking -> listening     <- 2.9s, no partials
#:     15:05:35,565  stt: timed out waiting for a transcript
#:
#: Four seconds is comfortably longer than any real gap inside one sentence --
#: the turn timer is 0.6 s -- so this only ever fires on audio that produced
#: nothing whatever, which is exactly the state worth clearing.
SILENT_RESET = 4.0


def _setting(name: str, fallback: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or fallback)
    except ValueError:
        log.warning("stt: %s is not a number; using %s", name, fallback)
        return fallback


def installed() -> bool:
    return all((MODEL_ROOT / name).is_file() for name in (WEIGHTS, MIMI, TOKENIZER, CONFIG))


class KyutaiUnavailableError(RuntimeError):
    """The checkpoint is not installed. Said, not guessed at."""


class _Model:
    """The recogniser, in its own process, one line of JSON per frame.

    Isolated rather than imported. Resolving `moshi` into the agent's
    environment replaces torch 2.13.0+cu130 with a 2.9.1 CPU wheel and
    downgrades numpy, safetensors and sounddevice with it -- which takes
    Kokoro's speech synthesis and every CUDA path in the agent down too. The
    two TTS engines are isolated for exactly this reason and this is the same
    boundary: PCM in, text out.
    """

    #: Long enough for a 2.3 GB checkpoint onto a card that may be busy.
    START_TIMEOUT = 240.0

    def __init__(self, model_dir: Path) -> None:
        if not installed():
            raise KyutaiUnavailableError(f"the Kyutai checkpoint is not at {model_dir}")
        uv = shutil.which("uv")
        if not uv:
            raise KyutaiUnavailableError("uv is required to start the Kyutai recogniser")
        repo = Path(__file__).resolve().parents[4]
        environment = os.environ.copy()
        # The agent runs inside a uv environment of its own, and passing
        # VIRTUAL_ENV into another `uv run --project` makes uv warn on every
        # start and can select the wrong environment outright.
        environment.pop("VIRTUAL_ENV", None)
        self._process = subprocess.Popen(
            [uv, "run", "--project", str(repo / PROJECT), "python", "-m", MODULE],
            cwd=repo,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            env=environment,
        )
        sidecars.track(self)
        ready = self._read()
        if ready.get("event") != "ready":
            self.release()
            raise KyutaiUnavailableError(str(ready.get("error") or "it did not start"))
        self.device = "sidecar"
        self.heads = int(ready.get("heads") or 0)
        self.delay_seconds = float(ready.get("delay_seconds") or 0.5)
        self.sample_rate = int(ready.get("sample_rate") or KYUTAI_SAMPLE_RATE)
        if self.sample_rate != KYUTAI_SAMPLE_RATE:
            # Said rather than resampled quietly: a rate mismatch here is a
            # different checkpoint, and guessing at it produces a recogniser
            # that transcribes confident nonsense.
            self.release()
            raise KyutaiUnavailableError(
                f"the Kyutai sidecar reports {self.sample_rate} Hz; "
                f"this adapter feeds {KYUTAI_SAMPLE_RATE} Hz"
            )
        if not self.heads:
            # Loadable and useless for the one thing this recogniser is for.
            # Said loudly rather than degrading into a worse Parakeet.
            log.warning(
                "stt: this Kyutai checkpoint carries no VAD heads; turn-taking "
                "falls back to the silence timer. Install stt-1b-en_fr-candle."
            )

    def _read(self) -> dict[str, Any]:
        # Held in a local for the whole call: `readline` blocks, `release` runs
        # on another thread, and reading the attribute again afterwards finds
        # nothing there. The TTS sidecar learned this the expensive way.
        process = self._process
        if process is None or process.stdout is None:
            raise KyutaiUnavailableError("the Kyutai recogniser is not running")
        line = process.stdout.readline()
        if not line:
            raise KyutaiUnavailableError(
                f"the Kyutai recogniser stopped unexpectedly ({process.poll()})"
            )
        return json.loads(line)

    def _ask(self, **request: Any) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdin is None:
            raise KyutaiUnavailableError("the Kyutai recogniser is not running")
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        return self._read()

    def reset(self) -> None:
        self._ask(op="reset")

    def step(self, samples: np.ndarray, first: bool) -> tuple[str, float]:
        """One frame in; the text it produced and the end-of-turn probability.

        `first` is the sidecar's business, not the caller's: it primes its own
        depformer after a reset. The parameter stays so the in-process shape
        and this one are interchangeable for the tests.
        """
        pcm = (np.clip(samples, -1.0, 1.0) * 32_767).astype(np.int16).tobytes()
        answer = self._ask(
            op="feed",
            pcm=base64.b64encode(pcm).decode("ascii"),
            vad_index=int(_setting(VAD_INDEX_SETTING, VAD_INDEX)),
        )
        if answer.get("event") == "error":
            raise KyutaiUnavailableError(str(answer.get("error")))
        return str(answer.get("text") or ""), float(answer.get("done") or 0.0)

    def flush(self, frames: int) -> tuple[str, float]:
        """`frames` of silence in one round trip; the text and the peak pause.

        Silence is how anything is got out of this model at the end: the text
        stream lags the audio by `audio_delay_seconds`, so the last words are
        still inside it when the speaker stops. Kyutai's own transcription
        script appends `ceil(audio_delay_seconds * frame_rate)` silent frames
        for exactly this and reads the tail off the end.

        Asked for in one call rather than seven, which is tidier and,
        measured, no faster: seven round trips took 156 ms and one round trip
        took 156 ms, because all of it is the model's seven steps and none of
        it is the pipe. Recorded here so nobody spends the afternoon again
        optimising a boundary that costs nothing. The 1.53 s this was blamed
        for is in `_settle`, and was never the flush.
        """
        answer = self._ask(
            op="flush",
            frames=int(frames),
            vad_index=int(_setting(VAD_INDEX_SETTING, VAD_INDEX)),
        )
        if answer.get("event") == "error":
            raise KyutaiUnavailableError(str(answer.get("error")))
        return str(answer.get("text") or ""), float(answer.get("done") or 0.0)

    def close(self) -> None:
        """The name the sidecar registry calls. `release` is the STT spelling."""
        self.release()

    def release(self) -> None:
        process, self._process = getattr(self, "_process", None), None
        if process is None:
            return
        # Asked to leave first: closing stdin ends the host's `for line in
        # sys.stdin` loop, which lets it free the model rather than being shot
        # holding it.
        with contextlib.suppress(Exception):
            if process.stdin:
                process.stdin.close()
        try:
            process.wait(timeout=2)
        except Exception:
            sidecars.kill_tree(process)
        else:
            # `uv run` may outlive the Python it started even when that one
            # exits cleanly.
            sidecars.kill_tree(process)
        sidecars.forget(self)


class KyutaiSTT(stt.STT):
    """Streaming recognition with an end-of-turn signal from the model itself."""

    def __init__(self, *, model_dir: Path | None = None) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True, interim_results=True, offline_recognize=False
            )
        )
        self._model_dir = model_dir or MODEL_ROOT
        self._model: _Model | None = None
        self._streams: set[KyutaiStream] = set()

    @property
    def model(self) -> str:
        return "kyutai-stt-1b-en_fr"

    @property
    def provider(self) -> str:
        return "kyutai"

    def prewarm(self) -> None:
        self._build()

    def _build(self) -> _Model:
        if self._model is not None:
            return self._model
        began = time.monotonic()
        self._model = _Model(self._model_dir)
        log.info(
            "stt: kyutai ready in %.1fs, %d VAD heads",
            time.monotonic() - began,
            self._model.heads,
        )
        return self._model

    async def _recognize_impl(self, *args: Any, **kwargs: Any) -> stt.SpeechEvent:
        raise NotImplementedError("KyutaiSTT is streaming-only")

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> KyutaiStream:
        stream = KyutaiStream(stt=self, conn_options=conn_options)
        self._streams.add(stream)
        return stream

    def set_transcribing(self, on: bool) -> None:
        for stream in tuple(self._streams):
            stream.set_transcribing(on)

    async def aclose(self) -> None:
        await asyncio.gather(*(stream.aclose() for stream in tuple(self._streams)))
        self._streams.clear()
        self.release()

    def release(self) -> None:
        """Hand the weights back to the card, so only one recogniser is resident."""
        if self._model is not None:
            self._model.release()
            self._model = None


class KyutaiStream(stt.RecognizeStream):
    """One utterance, ended by the model rather than by a stopwatch."""

    #: The ceiling. If the VAD never fires, this is exactly what every other
    #: recogniser here does, so the worst case is today's behaviour.
    _SILENCE = 0.6

    def __init__(self, *, stt: KyutaiSTT, conn_options: APIConnectOptions) -> None:
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=KYUTAI_SAMPLE_RATE)
        self._kyutai = stt
        self._said = ""
        self._spoke_at = time.monotonic()
        self._transcribing = True
        self._pending = np.zeros(0, dtype=np.float32)
        self._open = False
        self._first = True
        self._ended_by_vad = 0
        #: How many frames in a row the pause head has been over threshold.
        self._high_for = 0
        #: The highest it reached this turn, for the log. See `_settle`.
        self._peak = 0.0
        #: When this utterance opened, for `SILENT_RESET`.
        self._opened_at = time.monotonic()

    def set_transcribing(self, on: bool) -> None:
        self._transcribing = on

    def _emit(self, kind: stt.SpeechEventType, text: str) -> None:
        self._event_ch.send_nowait(
            stt.SpeechEvent(
                type=kind, alternatives=[stt.SpeechData(language="en", text=text)]
            )
        )

    def _begin(self, model: _Model) -> None:
        """Start an utterance, with the silence this model needs in front."""
        model.reset()
        self._first = False
        self._open = True
        self._high_for = 0
        self._peak = 0.0
        self._opened_at = time.monotonic()
        # One call, not twelve. Worth roughly nothing in time -- the twelve
        # model steps are the cost, not the twelve messages -- but this sits on
        # the critical path of every utterance and one operation there is
        # easier to reason about than a loop that can interleave with a reset.
        model.flush(int(PREFIX_SECONDS / FRAME_SECONDS))

    def _close(self, model: _Model) -> str:
        """The blocking half of ending a turn: flush, and hand back the words.

        Split from the emitting half because of where each has to run. This
        one blocks on the model and belongs on a worker thread; the emitting
        belongs on the event loop, and putting it here cost 1.53 s of silence
        after every sentence.
        """
        if not self._open:
            return ""
        # Flush past the model's own text delay, or the last words never
        # arrive: the text stream deliberately lags the audio by 0.5 s.
        tail, peak = model.flush(int(model.delay_seconds / FRAME_SECONDS) + 1)
        # Appended raw and stripped once, at the end. See `_drain`.
        self._said += tail
        self._peak = max(self._peak, peak)
        self._open = False
        said, self._said = self._said.strip(), ""
        self._pending = np.zeros(0, dtype=np.float32)
        return said

    async def _settle(self, model: _Model, why: str) -> None:
        """End the turn: the model on a thread, the events on the loop.

        `_settle` used to be one synchronous method run wholesale through
        `asyncio.to_thread`, emitting from in there. That is the bug behind the
        1.53 s between "turn ended by the timer" in the log and the transcript
        reaching the session.

        `Chan.send_nowait` appends to a deque and then wakes the waiting
        coroutine with `future.set_result` -- an asyncio call that is only
        valid on the loop's own thread. Called from a worker, the future is
        resolved but the loop is never signalled: it stays asleep in its
        selector until something *else* wakes it, and only then notices the
        transcript. Nothing is lost, so it looked like a slow model rather
        than a missed wakeup, and the flush wore the blame for it.

        `_drain` already had this right, and said so in a comment -- "Emission
        stays on the event loop, because `_event_ch.send_nowait` belongs to
        it". This is that rule applied to the other path.
        """
        said = await asyncio.to_thread(self._close, model)
        if said:
            self._said = said
            # What the heads actually did, every turn, whoever ended it.
            #
            # Head 2 answers "is a two-second pause starting" and the fallback
            # timer fires after 0.6 s of quiet, so the timer can win on
            # arithmetic alone and the model never gets to speak. Whether that
            # is what happens is a measurement, not a guess, and this is it:
            # how high the head reached against the bar it had to clear.
            log.info(
                "stt: turn ended by %s (pause head peaked at %.2f, needed %.2f for %d frames)",
                why,
                self._peak,
                _setting(VAD_THRESHOLD_SETTING, VAD_THRESHOLD),
                max(1, int(_setting(VAD_HOLD_SETTING, VAD_HOLD))),
            )
            self._emit(stt.SpeechEventType.FINAL_TRANSCRIPT, self._said)
            # And the event LiveKit acts on. Always, however the turn ended.
            #
            # This was emitted only when the pause heads called it, reasoning
            # that a turn ended by the fallback timer is an ordinary silence
            # ending and should not claim to be more. The reasoning was about
            # honesty; the effect was a deadlock. The session runs
            # `turn_detection="stt"` for this recogniser, and in that mode
            # `audio_recognition` has no other way to commit a turn:
            # `_vad_base_turn_detection` is false, and the VAD's own
            # end-of-speech runs the detector only `if self._turn_detection_mode
            # == "stt" and self._user_turn_committed` -- a flag set nowhere but
            # the branch this event feeds.
            #
            # So on every turn the heads stayed quiet for, the transcript was
            # delivered and nothing ever asked the LLM about it. Live: "Hey,
            # Marvi, how are you doing?" transcribed at 13:51:44, and Marvi
            # never answered for the remaining 86 seconds of the call. The turn
            # is over either way; which clock said so belongs in the log line
            # above, not in whether LiveKit is told.
            self._emit(stt.SpeechEventType.END_OF_SPEECH, "")
        self._said = ""
        self._peak = 0.0

    def _drain(self, model: _Model, threshold: float, hold: int) -> tuple[list[str], bool]:
        """Every complete frame in the buffer, on one worker thread.

        Returns the interim transcripts to emit and whether the model called
        the turn finished. Emission stays on the event loop, because
        `_event_ch.send_nowait` belongs to it; everything that blocks happens
        here.
        """
        said: list[str] = []
        while self._pending.size >= FRAME_SAMPLES:
            frame = self._pending[:FRAME_SAMPLES]
            self._pending = self._pending[FRAME_SAMPLES:]
            piece, done = model.step(frame, self._first)
            self._first = False
            if piece:
                # Appended raw. Stripping the whole transcript after every
                # piece looks harmless and eats word boundaries: this model
                # emits a bare space as a piece of its own, and
                # `("that's" + " ").strip()` is `"that's"`, so the next piece
                # lands against it. That is where
                #
                #     "that's a pretty good"  ->  "that'sa pretty good"
                #
                # came from, and with it "apretty", "thespeech", "outsearch"
                # and "Mybrilliant" all through one afternoon's transcripts --
                # then handed to the name corrector, which found "SaaS project"
                # inside "that'sa" and made it worse. Stripped once, where the
                # transcript is finished with.
                self._said += piece
                self._spoke_at = time.monotonic()
                said.append(self._said.strip())
            # Sustained, and only once something has been said.
            #
            # The heads are pause detectors: they are high through the silence
            # before anyone speaks, and they spike for a frame or two
            # mid-sentence. Both guards are load-bearing -- the first probe of
            # this signal, without them, would have ended one clip's turn 8.9
            # seconds early.
            self._peak = max(self._peak, done)
            self._high_for = self._high_for + 1 if done > threshold else 0
            if self._said and self._high_for >= hold:
                return said, True
        return said, False

    async def _run(self) -> None:
        model = await asyncio.to_thread(self._kyutai._build)
        threshold = _setting(VAD_THRESHOLD_SETTING, VAD_THRESHOLD)
        hold = max(1, int(_setting(VAD_HOLD_SETTING, VAD_HOLD)))
        try:
            async for item in self._input_ch:
                if isinstance(item, self._FlushSentinel):
                    await self._settle(model, "flush")
                    continue
                samples = np.frombuffer(bytes(item.data), dtype=np.int16)
                if not samples.size or not self._transcribing:
                    continue
                self._pending = np.concatenate(
                    [self._pending, samples.astype(np.float32) / 32_768.0]
                )
                if not self._open:
                    await asyncio.to_thread(self._begin, model)
                # Every whole frame in one hop, not one hop per frame.
                #
                # This awaited `asyncio.to_thread(model.step, ...)` per 80 ms
                # frame, and each of those is a thread handoff plus a JSON
                # write and a blocking `readline` on the sidecar's pipe. At
                # 12.5 frames a second, serially awaited, that is 12.5 round
                # trips through an executor the LiveKit runtime is also using
                # -- so the cost is not the 36 ms of model time measured in
                # isolation, it is that plus however long a worker takes to
                # come free while the same loop is running the VAD and the
                # speech synthesis.
                #
                # The log shows what that did live: partials trickling one word
                # at a time, then `silero: inference is slower than realtime,
                # delay 1.497s`, then the transcript timeout firing and Marvi
                # apologising while the sentence was still arriving. Starving
                # the VAD is how a slow recogniser becomes a broken turn.
                said, finished = await asyncio.to_thread(
                    self._drain, model, threshold, hold
                )
                for text in said:
                    self._emit(stt.SpeechEventType.INTERIM_TRANSCRIPT, text)
                if finished:
                    self._ended_by_vad += 1
                    await self._settle(model, "the model")
                elif self._said and time.monotonic() - self._spoke_at >= self._SILENCE:
                    await self._settle(model, "the timer")
                elif (
                    self._open
                    and not self._said
                    and time.monotonic() - self._opened_at >= SILENT_RESET
                ):
                    # Heard, and nothing came of it. `_settle` emits nothing
                    # for an empty transcript -- silence is not a turn -- but
                    # it is also the only thing that resets the model, and
                    # leaving it open carries this state into the next
                    # utterance. See `SILENT_RESET`.
                    await self._settle(model, "nothing heard")
        finally:
            with contextlib.suppress(Exception):
                await self._settle(model, "close")
