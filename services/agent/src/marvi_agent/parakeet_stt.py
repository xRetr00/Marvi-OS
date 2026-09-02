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
16.8%. It is in Settings.

I previously wrote here that the lookahead does not delay the turn because the
last chunk is flushed as soon as speech stops. The session log disagrees:
short utterances -- "Can you check the room status?" -- wait 3.3s for a final
transcript, while long ones wait a tenth of that. The first block needs a
chunk plus the lookahead, four seconds, before anything is decoded at all, so
a short utterance produces no text until the flush. The flush itself measures
300-420ms, which does not account for the rest, so the cause is not yet
established and `_settle` now logs what it would take to establish it.
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
#: The English-only export, when it is installed. Optional, 2.5GB.
PARAKEET_ENGLISH_ROOT = APP_DATA / "models/stt/parakeet-tdt-0.6b-v2-onnx"

#: What the desktop writes when recognition is set to English only.
LANGUAGE_SETTING = "MARVI_STT_LANGUAGE"


ENGINE_SETTING = "MARVI_STT_ENGINE"

#: The recognisers Marvi can be told to use, and what each one is for.
#:
#: Measured 2 September 2026 over 162 EdAcc clips, 2,158 reference words:
#:
#:     parakeet-tdt   WER 20.81%  RTF 0.055  first partial 2,910 ms
#:     nemotron-3.5   WER 24.79%  RTF 0.090  first partial 1,063 ms
#:     kyutai-1b      WER 35.26%  RTF 0.80   first partial 3,521 ms
#:
#: Four points of word error against 1.8 seconds off the first word. Neither
#: is better; they are different trades, so both are offered and the more
#: accurate one is the default.
#:
#: Kyutai loses on both of those numbers and is here for a third one the other
#: two cannot produce at all: it says when the speaker has finished, from
#: content and intonation, instead of leaving turn-taking to a 600 ms timer.
#: See `kyutai_stt`.
ENGINES = ("parakeet-tdt", "nemotron-3.5", "kyutai-1b")


def chosen_engine() -> str:
    """Which recogniser, from the setting. Falls back to the default."""
    wanted = os.environ.get(ENGINE_SETTING, "").strip().lower()
    return wanted if wanted in ENGINES else ENGINES[0]


def build_stt(engine: str = "") -> Any:
    """The selected recogniser, or the default when the choice cannot be met.

    Falls back rather than raising, and says so. A recogniser that will not
    load is a Marvi that cannot hear at all, which is worse than a Marvi
    hearing you through her second choice -- and the Voice page names the one
    actually running, so the fallback is visible rather than silent.
    """
    selected = (engine or chosen_engine()).strip().lower()
    if selected == "nemotron-3.5":
        from .nemotron_stt import NemotronSTT, installed

        if installed():
            return NemotronSTT()
        log.warning("stt: nemotron is selected but not installed; using parakeet")
    if selected == "kyutai-1b":
        from .kyutai_stt import KyutaiSTT
        from .kyutai_stt import installed as kyutai_installed

        if kyutai_installed():
            return KyutaiSTT()
        log.warning("stt: kyutai is selected but not installed; using parakeet")
    return ParakeetSTT()


def chosen_model() -> Path:
    """Which recogniser to load, from the language setting.

    The only real language lock there is. v3 recognises twenty-five languages
    and takes no argument to narrow that -- NVIDIA's card says it detects the
    language itself, and the request for a parameter was closed without one.
    So an accented sentence, or one foreign word, comes back as a line of
    another language, and the model then answers in it. A prompt saying
    "reply in English" is one sentence against the whole visible conversation,
    and it loses.

    v2 has no other language in its vocabulary. It cannot make that mistake.

    Falls back to v3 when English is asked for and v2 was never installed:
    hearing you in a model that guesses is better than not hearing you, and the
    settings page is where that gets said rather than here.
    """
    if os.environ.get(LANGUAGE_SETTING, "").strip().lower() != "en":
        return PARAKEET_ROOT
    if (PARAKEET_ENGLISH_ROOT / "encoder-model.onnx").exists():
        return PARAKEET_ENGLISH_ROOT
    log.warning(
        "stt: English-only recognition is selected but %s is not installed; "
        "using the multilingual model, which decides the language for itself. "
        "Install it from Settings > Speech recognition.",
        PARAKEET_ENGLISH_ROOT.name,
    )
    return PARAKEET_ROOT

SAMPLE_RATE = 16_000

#: How much of the future the recogniser sees before committing a word.
#:
#: Two seconds measured 13.7% word errors and eight tenths measured 16.8%, so
#: this buys accuracy with lag on the live transcript rather than with anything
#: the turn waits for.
DEFAULT_LOOKAHEAD = 2.0
#: How much audio it takes at a time.
#:
#: The comment here used to say "larger is slightly faster and no more
#: accurate; the lookahead is the dial that matters". True of accuracy and
#: badly wrong about latency: a partial cannot exist before its chunk is full,
#: so this is the *floor* on how soon a word can appear on screen. Measured on
#: 200 voice-agent clips, first useful partial at the median:
#:
#:     chunk 2.0s  lookahead 2.0s   4,115 ms   WER 3.44%   clean 71%
#:     chunk 2.0s  lookahead 0.8s   2,913 ms   WER 4.19%   clean 66%
#:
#: Two seconds of that is this constant, and no lookahead setting can reach it.
#: Settable for the same reason the lookahead is: which trade is right depends
#: on whether somebody is dictating or talking.
DEFAULT_CHUNK = 2.0

#: How much of the past the encoder re-reads on every chunk.
#:
#: This is what the final flush pays for, and the final flush is the dead air
#: between somebody finishing a sentence and Marvi knowing what they said.
#: Measured on this machine with a full buffer:
#:
#:     left  10.0s   flush 1591ms
#:     left   6.0s   flush  995ms
#:     left   4.0s   flush  918ms
#:     left   2.0s   flush  565ms
#:
#: And measured for accuracy on synthesised English, four sentences, scored
#: against the text they were made from: 2.3% word errors at every one of those
#: settings. Identical -- so on this material the window buys nothing and costs
#: two thirds of a second per turn.
#:
#: Four rather than two, because that is where the latency curve flattens and
#: because the accuracy check has a real limit worth naming: synthesised speech
#: is easy audio. The 13.7% that chose this recogniser was measured on accented
#: human speech, and that corpus is gone. If accented accuracy drops, this
#: constant is the first thing to put back.
DEFAULT_LEFT_CONTEXT = 4.0


def lookahead_seconds() -> float:
    try:
        return max(0.2, min(float(os.environ.get("MARVI_STT_LOOKAHEAD") or DEFAULT_LOOKAHEAD), 4.0))
    except ValueError:
        return DEFAULT_LOOKAHEAD


def chunk_seconds() -> float:
    """How much audio the recogniser takes at a time, from the setting.

    Bounded at half a second because below that the encoder is re-reading four
    seconds of left context for every fragment and the throughput cost stops
    being worth the latency, and at four because past that the first word is
    slower than anybody will sit through.
    """
    try:
        return max(0.5, min(float(os.environ.get("MARVI_STT_CHUNK") or DEFAULT_CHUNK), 4.0))
    except ValueError:
        return DEFAULT_CHUNK


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

    def __init__(self, *, model_dir: Path | None = None) -> None:
        model_dir = model_dir or chosen_model()
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
        # From the directory actually loaded, not a constant. The Voice page
        # reads this, and a page that names v3 while v2 is running is the
        # reason nobody could tell which language rule was in force.
        return self._model_dir.name.removesuffix("-onnx")

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
            chunk_secs=chunk_seconds(),
            left_context_secs=DEFAULT_LEFT_CONTEXT,
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
        self.release()

    def release(self) -> None:
        """Let go of the ONNX sessions.

        A warmed recogniser that nobody will use again is not free: the CUDA
        execution provider holds its device memory for as long as the session
        object lives, and the process that built it outlives any one call. With
        one model that never mattered, because the same one was wanted next
        time. With a choice of recogniser it does -- see `build_session`, which
        drops a warmed recogniser whose model is not the selected one.
        """
        self._asr = None


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
                    await self._feed(asr, block, False)
                    self._heard(asr)
                    want = asr.chunk_samples

                if self._transcript.strip() and (
                    time.monotonic() - self._spoke_at >= self._SILENCE
                ):
                    await self._settle(asr)
        finally:
            # Closing must not raise: the stream is already going away.
            with contextlib.suppress(Exception):
                await self._settle(asr)

    def _heard(self, asr: Any) -> None:
        """Re-read the whole utterance instead of gluing the deltas together.

        `process_chunk` returns the text of the tokens decoded in *that chunk*,
        with its own leading space stripped. A word split across a chunk
        boundary therefore comes back as "actu" then "ally", and joining those
        with a space gave "actu ally". Real transcripts: "say ing",
        "Troubles hooting", "se arch", "this .". The recogniser heard correctly
        every time; the transcript was assembled wrongly.

        The decoder keeps every token of the utterance, so asking it for the
        whole text puts the SentencePiece word boundaries back where the model
        put them. Cheap: a list lookup per token over one sentence.
        """
        text = asr.get_full_text().strip()
        if not text or text == self._transcript:
            return
        self._transcript = text
        self._spoke_at = time.monotonic()
        self._emit(stt.SpeechEventType.INTERIM_TRANSCRIPT, text)

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
        held = self._pending.size / SAMPLE_RATE
        began = time.monotonic()
        await self._feed(asr, self._pending, True)
        self._heard(asr)
        self._pending = np.zeros(0, dtype=np.float32)
        if not self._transcript.strip():
            return
        # Short utterances show up to 3.3s of `transcription_delay` in the
        # session log and long ones near zero, which points at the four seconds
        # of audio the first block needs before anything is decoded. The flush
        # itself measures 300-420ms on the processor, so it does not account
        # for the gap; these two numbers say whether the wait is ours.
        log.info(
            "stt: settled %.1fs of held audio in %dms",
            held,
            (time.monotonic() - began) * 1000,
        )
        self._emit(stt.SpeechEventType.FINAL_TRANSCRIPT, self._transcript.strip())
        self._transcript = ""
        self._first = True
        # The decoder carries state across chunks -- that is what makes it
        # incremental -- so an utterance that ends without clearing it leaves
        # the next one continuing the last.
        if hasattr(asr, "reset"):
            asr.reset()
