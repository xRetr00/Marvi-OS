"""Speech recognition: Parakeet TDT, fed in chunks.

Measured on 54 clips of English spoken by people who did not grow up speaking
it -- the Edinburgh corpus, nine first languages, spontaneous conversation:

    Parakeet streaming (this)   13.7% word errors
    Nemotron 3.5 (before)       22.0%
    Moonshine v2 base           27.3%
    Voxtral Mini Realtime       29.2%

The previous engine was not a bad choice on paper. It benchmarks at 6.93% on
the public leaderboards against Parakeet's 6.32%, which is close enough to be a
coin toss -- and on accented speech the gap opens to nearly a third fewer
errors. Leaderboards are measured on clean, mostly native reading. That is not
the job.

**Why it can run off the card.** This is ONNX Runtime and numpy, with no
PyTorch or NeMo of its own, so it is the one component here that can be pointed
at the CPU and still keep up: 3.8x real time on the processor, 14.6x on the
card, and identical accuracy either way. On the processor it stops competing
with speech synthesis for a single GPU, which is what made replies stutter.
Hence a setting rather than a decision.

**The lookahead is the only real trade.** The recogniser sees a little of the
future before committing a word: two seconds gives 13.7%, eight tenths gives
16.8%. That window is how far the live transcript runs behind the voice -- it
does not delay the *turn*, because the last chunk is flushed the moment speech
stops. So it is a subtitle-smoothness dial, and it is in Settings.
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

log = logging.getLogger("marvi.voice")

APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Marvi-OS"
#: Where the installer puts the ONNX export. Matches `install_to` in the setup
#: catalog; a test pins the two together.
PARAKEET_ROOT = APP_DATA / "models/stt/parakeet-tdt-0.6b-v3-onnx"

SAMPLE_RATE = 16_000

#: How much of the future the recogniser sees before committing a word.
#:
#: Two seconds measured 13.7% word errors and eight tenths measured 16.8%, so
#: this buys accuracy with lag on the live transcript rather than with anything
#: the turn waits for.
DEFAULT_LOOKAHEAD = 2.0
#: How much audio it takes at a time. Larger is slightly faster and no more
#: accurate; the lookahead is the dial that matters.
DEFAULT_CHUNK = 2.0


def lookahead_seconds() -> float:
    try:
        return max(0.2, min(float(os.environ.get("MARVI_STT_LOOKAHEAD") or DEFAULT_LOOKAHEAD), 4.0))
    except ValueError:
        return DEFAULT_LOOKAHEAD


def providers() -> list[str]:
    """Execution providers, from the setting.

    ONNX Runtime wants CUDA 13's cuBLAS and cuDNN 9, which are not installed
    system-wide on a normal Windows machine. Torch 2.13+cu130 ships exactly
    those and is already here for the speech synthesis, so importing it first
    puts them on the process's DLL search path. That is the whole trick, and
    without it the CUDA provider silently falls back to the processor -- which
    looks like a setting that does nothing.
    """
    if os.environ.get("MARVI_STT_DEVICE", "cpu").strip().lower() != "cuda":
        return ["CPUExecutionProvider"]
    try:
        import torch  # noqa: F401 - imported for its CUDA libraries, not its API
    except Exception as exc:  # pragma: no cover - depends on the install
        log.warning("no torch to borrow CUDA libraries from (%s); using the CPU", exc)
        return ["CPUExecutionProvider"]
    return ["CUDAExecutionProvider", "CPUExecutionProvider"]


class ParakeetSTT(stt.STT):
    """Streaming recognition, one recogniser shared by every stream."""

    def __init__(self, *, model_dir: Path = PARAKEET_ROOT) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True,
                interim_results=True,
                # `recognize()` raises here. A capability declared and not
                # implemented is a fault waiting for a caller.
                offline_recognize=False,
            )
        )
        self._model_dir = model_dir
        self._asr: Any = None
        self._streams: set[ParakeetStream] = set()

    @property
    def model(self) -> str:
        return "parakeet-tdt-0.6b-v3"

    @property
    def provider(self) -> str:
        return "nvidia/onnx"

    def prewarm(self) -> None:
        """Build the sessions before a call rather than during one."""
        self._build()

    def _build(self) -> Any:
        if self._asr is not None:
            return self._asr
        from streaming.streaming_asr import StreamingTdtASR

        began = time.monotonic()
        chosen = providers()
        self._asr = StreamingTdtASR(
            str(self._model_dir),
            chunk_secs=DEFAULT_CHUNK,
            left_context_secs=10.0,
            right_context_secs=lookahead_seconds(),
            providers=chosen,
        )
        log.info(
            "stt: parakeet ready in %.1fs on %s, %.1fs lookahead",
            time.monotonic() - began,
            chosen[0].replace("ExecutionProvider", "").lower(),
            lookahead_seconds(),
        )
        return self._asr

    async def _recognize_impl(self, *args: Any, **kwargs: Any) -> stt.SpeechEvent:
        raise NotImplementedError("ParakeetSTT is streaming-only")

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> ParakeetStream:
        stream = ParakeetStream(stt=self, conn_options=conn_options)
        self._streams.add(stream)
        return stream

    def set_transcribing(self, on: bool) -> None:
        """Kept for the session's sake, and now nearly pointless.

        The recogniser was paused while Marvi spoke because both models wanted
        one GPU. On the processor there is nothing to yield, so this only still
        exists for a machine configured to run both on the card.
        """
        for stream in tuple(self._streams):
            stream.set_transcribing(on)

    async def aclose(self) -> None:
        await asyncio.gather(*(stream.aclose() for stream in tuple(self._streams)))
        self._streams.clear()


class ParakeetStream(stt.RecognizeStream):
    """One utterance at a time, in chunks, with the tail flushed at the end."""

    #: Silence after speech before the utterance is called finished. Nothing
    #: else declares a transcript final: LiveKit flushes the VAD and waits for
    #: the recogniser to say the sentence ended.
    _SILENCE = 0.6

    def __init__(self, *, stt: ParakeetSTT, conn_options: APIConnectOptions) -> None:
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=SAMPLE_RATE)
        self._parakeet = stt
        self._transcript = ""
        self._spoke_at = time.monotonic()
        self._transcribing = True
        self._pending = np.zeros(0, dtype=np.float32)
        self._first = True

    def set_transcribing(self, on: bool) -> None:
        self._transcribing = on

    def _emit(self, event_type: stt.SpeechEventType, text: str) -> None:
        self._event_ch.send_nowait(
            stt.SpeechEvent(
                type=event_type,
                request_id="",
                alternatives=[stt.SpeechData(language="en", text=text)],
            )
        )

    async def _feed(self, asr: Any, block: np.ndarray, last: bool) -> str:
        """One block through the recogniser, off the event loop.

        ONNX inference is CPU-or-GPU bound and blocking either way; running it
        inline would stall the audio the session is still receiving.
        """
        return await asyncio.to_thread(asr.process_chunk, block, last)

    async def _run(self) -> None:
        asr = await asyncio.to_thread(self._parakeet._build)
        # The first call wants a chunk plus the lookahead; every call after it
        # wants exactly a chunk. Read off the recogniser rather than computed
        # from seconds, because the model works on an 80ms frame grid and a
        # request that is not a whole number of frames is refused.
        try:
            async for item in self._input_ch:
                if isinstance(item, self._FlushSentinel):
                    await self._settle(asr)
                    continue

                samples = np.frombuffer(bytes(item.data), dtype=np.int16)
                if not samples.size or not self._transcribing:
                    continue
                self._pending = np.concatenate(
                    [self._pending, samples.astype(np.float32) / 32767.0]
                )

                want = asr._initial_samples_needed if self._first else asr.chunk_samples
                while self._pending.size >= want:
                    block, self._pending = self._pending[:want], self._pending[want:]
                    self._first = False
                    delta = await self._feed(asr, block, False)
                    self._heard(delta)
                    want = asr.chunk_samples

                if self._transcript.strip() and (
                    time.monotonic() - self._spoke_at >= self._SILENCE
                ):
                    await self._settle(asr)
        finally:
            # Closing must not raise: the stream is already going away.
            with contextlib.suppress(Exception):
                await self._settle(asr)

    def _heard(self, delta: str) -> None:
        if not delta.strip():
            return
        self._transcript = (self._transcript + " " + delta.strip()).strip()
        self._spoke_at = time.monotonic()
        self._emit(stt.SpeechEventType.INTERIM_TRANSCRIPT, self._transcript)

    async def _settle(self, asr: Any) -> None:
        """End the utterance: flush whatever is held and start clean.

        The tail matters. Held audio shorter than a chunk is still words, and
        without the final flush the last few of every sentence are lost.
        """
        # Always, even with nothing held back. The recogniser buffers audio of
        # its own and only releases it when told this is the last block, so
        # skipping the call when the queue happens to be empty loses the end of
        # the sentence -- "the third piece, the conversation" became "the
        # third".
        self._heard(await self._feed(asr, self._pending, True))
        self._pending = np.zeros(0, dtype=np.float32)
        if not self._transcript.strip():
            return
        self._emit(stt.SpeechEventType.FINAL_TRANSCRIPT, self._transcript.strip())
        self._transcript = ""
        self._first = True
        # The decoder carries state across chunks -- that is what makes it
        # incremental -- so an utterance that ends without clearing it leaves
        # the next one continuing the last.
        if hasattr(asr, "reset"):
            asr.reset()
