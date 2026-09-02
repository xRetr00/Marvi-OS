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
import contextlib
import logging
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
from livekit.agents import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions, stt
from livekit.agents.types import NOT_GIVEN, NotGivenOr

from .parakeet_stt import APP_DATA, SAMPLE_RATE

log = logging.getLogger("marvi.voice")

MODEL_ROOT = APP_DATA / "models/stt/kyutai-stt-1b-candle"

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

#: Mimi's frame. The model consumes exactly this much audio per step and
#: nothing else is a valid feed size.
FRAME_SECONDS = 0.08
FRAME_SAMPLES = int(FRAME_SECONDS * SAMPLE_RATE)

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
    """Mimi, the language model and the tokenizer, loaded once per process."""

    def __init__(self, model_dir: Path) -> None:
        if not installed():
            raise KyutaiUnavailableError(f"the Kyutai checkpoint is not at {model_dir}")
        # Triton has no Windows build, and `moshi` reaches for `torch.compile`
        # unless told not to. Eager is what the benchmark measured.
        os.environ.setdefault("NO_TORCH_COMPILE", "1")
        import torch
        from moshi.models import LMGen, loaders

        self._torch = torch
        checkpoint = loaders.CheckpointInfo.from_hf_repo(
            "kyutai/stt-1b-en_fr-candle",
            config_path=model_dir / CONFIG,
            moshi_weights=model_dir / WEIGHTS,
            mimi_weights=model_dir / MIMI,
            tokenizer=model_dir / TOKENIZER,
        )
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self.mimi = checkpoint.get_mimi(device=device)
        self.tokenizer = checkpoint.get_text_tokenizer()
        self.lm = checkpoint.get_moshi(device=device)
        self.gen = LMGen(self.lm, temp=0, temp_text=0, use_sampling=False)
        self.device = device
        self.delay_seconds = float(checkpoint.stt_config.get("audio_delay_seconds", 0.5))
        self.heads = len(getattr(self.lm, "extra_heads", ()) or ())
        if not self.heads:
            # Loadable and useless for the one thing this recogniser is for.
            # Said loudly rather than degrading into a worse Parakeet.
            log.warning(
                "stt: this Kyutai checkpoint carries no VAD heads; turn-taking "
                "falls back to the silence timer. Install stt-1b-en_fr-candle."
            )
        self.mimi.streaming_forever(1)
        self.gen.streaming_forever(1)

    def reset(self) -> None:
        self.mimi.reset_streaming()
        self.gen.reset_streaming()

    def step(self, samples: np.ndarray, first: bool) -> tuple[str, float]:
        """One frame in; the text it produced and the end-of-turn probability."""
        torch = self._torch
        with torch.inference_mode():
            chunk = torch.from_numpy(samples).to(self.device)[None, None, :]
            codes = self.mimi.encode(chunk)
            if first:
                # The first step primes the depformer and returns nothing
                # usable; upstream's own loop does the same.
                self.gen.step(codes)
            found = self.gen.step_with_extra_heads(codes)
            if found is None:
                return "", 0.0
            tokens, heads = found
            index = int(_setting(VAD_INDEX_SETTING, VAD_INDEX))
            done = 0.0
            if heads and 0 <= index < len(heads):
                # Element 0 of the head's softmax is the probability of a pause
                # of that length. `prs[2][0] > 0.5` is Kyutai's own test.
                done = float(heads[index][0, 0, 0].item())
            token = int(tokens[0, 0].item())
            if token in (0, 3):
                return "", done
            return self.tokenizer.id_to_piece(token).replace("▁", " "), done

    def release(self) -> None:
        for name in ("gen", "lm", "mimi"):
            with contextlib.suppress(Exception):
                delattr(self, name)
        with contextlib.suppress(Exception):
            self._torch.cuda.empty_cache()


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
            "stt: kyutai ready in %.1fs on %s, %d VAD heads",
            time.monotonic() - began,
            self._model.device,
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
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=SAMPLE_RATE)
        self._kyutai = stt
        self._said = ""
        self._spoke_at = time.monotonic()
        self._transcribing = True
        self._pending = np.zeros(0, dtype=np.float32)
        self._open = False
        self._first = True
        self._ended_by_vad = 0

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
        self._first = True
        self._open = True
        quiet = np.zeros(FRAME_SAMPLES, dtype=np.float32)
        for _ in range(int(PREFIX_SECONDS / FRAME_SECONDS)):
            model.step(quiet, self._first)
            self._first = False

    def _settle(self, model: _Model, why: str) -> None:
        if not self._open:
            return
        # Flush past the model's own text delay, or the last words never
        # arrive: the text stream deliberately lags the audio by 0.5 s.
        quiet = np.zeros(FRAME_SAMPLES, dtype=np.float32)
        for _ in range(int(model.delay_seconds / FRAME_SECONDS) + 1):
            piece, _done = model.step(quiet, False)
            if piece:
                self._said = (self._said + piece).strip()
        self._open = False
        if self._said:
            log.info("stt: turn ended by %s", why)
            self._emit(stt.SpeechEventType.FINAL_TRANSCRIPT, self._said)
        self._said = ""
        self._pending = np.zeros(0, dtype=np.float32)

    async def _run(self) -> None:
        model = await asyncio.to_thread(self._kyutai._build)
        threshold = _setting(VAD_THRESHOLD_SETTING, VAD_THRESHOLD)
        try:
            async for item in self._input_ch:
                if isinstance(item, self._FlushSentinel):
                    await asyncio.to_thread(self._settle, model, "flush")
                    continue
                samples = np.frombuffer(bytes(item.data), dtype=np.int16)
                if not samples.size or not self._transcribing:
                    continue
                self._pending = np.concatenate(
                    [self._pending, samples.astype(np.float32) / 32_768.0]
                )
                if not self._open:
                    await asyncio.to_thread(self._begin, model)
                finished = False
                while self._pending.size >= FRAME_SAMPLES:
                    frame = self._pending[:FRAME_SAMPLES]
                    self._pending = self._pending[FRAME_SAMPLES:]
                    piece, done = await asyncio.to_thread(model.step, frame, self._first)
                    self._first = False
                    if piece:
                        self._said = (self._said + piece).strip()
                        self._spoke_at = time.monotonic()
                        self._emit(stt.SpeechEventType.INTERIM_TRANSCRIPT, self._said)
                    # Only once something has been said. The pause heads spike
                    # on digits and on audio the model reads as silence, and an
                    # end-of-turn before the first word is not a turn ending.
                    if self._said and done > threshold:
                        finished = True
                        break
                if finished:
                    self._ended_by_vad += 1
                    await asyncio.to_thread(self._settle, model, "the model")
                elif self._said and time.monotonic() - self._spoke_at >= self._SILENCE:
                    await asyncio.to_thread(self._settle, model, "the timer")
        finally:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._settle, model, "close")
