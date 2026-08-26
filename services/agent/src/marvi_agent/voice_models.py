from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
from livekit.agents import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions, tts

log = logging.getLogger("marvi.voice")

APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Marvi-OS"
NEMOTRON_MODEL = (
    APP_DATA / "models/stt/nemotron-3.5/nemotron-3.5-asr-streaming-0.6b-onnx"
)
#: Where the installer puts Kokoro. Matches `install_to` in the setup
#: catalog; the test below fails if the two drift.
KOKORO_ROOT = APP_DATA / "models/tts/kokoro-82m"

#: Kokoro ships fixed voices rather than speaker prompts. `a` is American
#: English, `b` British; the letter after the underscore is the model's own
#: naming, not a grade.
KOKORO_VOICES = (
    "af_heart",
    "af_bella",
    "af_nicole",
    "af_sarah",
    "af_sky",
    "am_adam",
    "am_michael",
    "bf_emma",
    "bf_isabella",
    "bm_george",
    "bm_lewis",
)
KOKORO_DEFAULT_VOICE = "am_michael"
#: One loaded model per voice for the life of the process.
#:
#: LiveKit runs jobs as threads on Windows and prewarms a replacement the
#: moment a job takes the warm one, so without this a second copy of the
#: weights loads onto the card partway through every conversation.
_KOKORO: dict[tuple[str, str, int], _KokoroEngine] = {}
_ENGINE_LOCK = threading.Lock()


class VoiceRuntimeError(RuntimeError):
    pass


def to_pcm(audio: Any) -> tuple[bytes, int]:
    """One buffer of float samples as 24 kHz mono int16, and how many clipped.

    Clipped, never normalised, and that is the whole reason it is its own
    function. This used to divide each buffer by its own peak whenever that peak
    exceeded one -- per buffer, so one peaking at 1.4 was scaled down and the
    next, peaking at 0.9, was not. A step in gain at the boundary between them
    is a discontinuity in the middle of a waveform, which is a click, and a
    click at every buffer boundary is speech that shatters.

    Nothing about where the model hands over a buffer means anything
    acoustically. Clipping the rare overshoot distorts a few samples; rescaling
    the audio either side of an arbitrary line distorts every boundary.
    """
    over = int(np.count_nonzero(np.abs(audio) > 1.0))
    return (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes(), over


def resolve_voice(voice: str) -> str:
    """A voice this engine actually has, whatever was asked for.

    Every install that has run Marvi before carries a VibeVoice speaker name in
    its settings -- `en-Carter_man` and the like -- and Kokoro has never heard
    of it. Handing that through would raise on the first spoken turn of the
    first session after an update: voice silently dead, for a reason nowhere
    near where it would be looked for.

    So an unknown name falls back and says so, once, rather than failing.
    """
    if voice in KOKORO_VOICES:
        return voice
    if voice:
        log.warning(
            "unknown voice %r; speaking as %s. Pick one in Settings: %s",
            voice,
            KOKORO_DEFAULT_VOICE,
            ", ".join(KOKORO_VOICES),
        )
    return KOKORO_DEFAULT_VOICE


class _KokoroEngine:
    """Kokoro, behind the same interface the streaming adapter already drives.

    Chosen on measurement rather than on size. On this card, same sentence:

        Kokoro 82M       34.72x real time, first sound 234ms,  709MB
        VibeVoice 0.5B    1.17x real time, first sound 144ms, 2685MB
        Chatterbox        0.97x real time, first sound 6406ms
        Qwen3-TTS 0.6B    0.33x real time, first sound 31922ms

    VibeVoice is not slow -- it clears real time alone, and reaches the first
    sound soonest of the four because it genuinely streams. What it does not
    have is margin. Seventeen percent disappears the moment the recogniser
    wants the same card, which is exactly what happened: in a real session it
    measured 0.80x, and below one the room runs out of audio and the reply
    arrives in pieces. Thirty-four times cannot be pushed under one by anything
    Marvi will plausibly run beside it.

    One pipeline per voice for the life of the process, for the same reason the
    other engine caches: a second copy is a second copy of the weights.
    """

    sample_rate = 24_000

    def __init__(self, voice: str = KOKORO_DEFAULT_VOICE) -> None:
        self.voice = resolve_voice(voice)
        self._pipeline: Any = None
        self._speaking = threading.Lock()

    @classmethod
    def shared(cls, voice: str) -> _KokoroEngine:
        key = ("kokoro", resolve_voice(voice), 0)
        with _ENGINE_LOCK:
            engine = _KOKORO.get(key)
            if engine is None:
                engine = cls(voice)
                _KOKORO[key] = engine
            return engine

    @property
    def voices(self) -> list[str]:
        return list(KOKORO_VOICES)

    def load(self) -> None:
        if self._pipeline is not None:
            return
        import torch
        from kokoro import KModel, KPipeline

        device = "cuda" if torch.cuda.is_available() else "cpu"
        # From the installed files, not from the network.
        #
        # Kokoro fetches its own weights from Hugging Face on first use, which
        # would mean the installer downloads 318MB and then the first spoken
        # turn downloads it again -- and an offline machine never speaks at
        # all. The installer already puts it somewhere known; this reads it
        # from there, and falls back to Kokoro's own downloading for a
        # checkout that never ran the installer.
        weights = KOKORO_ROOT / "kokoro-v1_0.pth"
        config = KOKORO_ROOT / "config.json"
        if weights.is_file() and config.is_file():
            model = KModel(config=str(config), model=str(weights)).to(device).eval()
        else:
            log.info("no installed Kokoro at %s; fetching it", KOKORO_ROOT)
            model = True  # KPipeline builds and downloads its own

        # `lang_code="a"` is Kokoro's American English. The voice carries the
        # accent; this selects the grapheme-to-phoneme rules.
        self._pipeline = KPipeline(lang_code="a", model=model, device=device)
        self._seed_voice(torch, device)
        # The first call compiles and warms. Doing it here keeps it off the
        # first spoken turn, which is where it would be felt.
        list(self._pipeline("Warm up.", voice=self.voice))

    def _seed_voice(self, torch: Any, device: str) -> None:
        """Put the installed speaker in the pipeline's cache under its name.

        Same reason as the weights: the voices are part of what the installer
        fetched, and Kokoro downloads each one again the first time it is used
        otherwise.

        Seeded rather than passed in. `load_voice` does return a tensor
        unchanged -- but only after `isinstance(voice, torch.FloatTensor)`,
        which is a legacy type that a modern float tensor is not an instance
        of. So the tensor falls through to `voice.split(",")`, meant for
        blending two speakers by name, and a tensor's `.split` takes sizes:

            TypeError: split_with_sizes(): argument 'split_sizes' must be
                       tuple of ints, not str

        The cache is checked before any of that.
        """
        path = KOKORO_ROOT / "voices" / f"{self.voice}.pt"
        if not path.is_file():
            return
        self._pipeline.voices[self.voice] = torch.load(
            path, map_location=device, weights_only=True
        )

    def synthesize(self, text: str, stop: threading.Event) -> Iterator[bytes]:
        with self._speaking:
            yield from self._synthesize(text, stop)

    def _synthesize(self, text: str, stop: threading.Event) -> Iterator[bytes]:
        self.load()
        for _graphemes, _phonemes, audio in self._pipeline(text, voice=self.voice):
            if stop.is_set():
                break
            samples = np.asarray(audio, dtype=np.float32).reshape(-1)
            pcm, over = to_pcm(samples)
            if over:
                log.info("tts: %d samples clipped", over)
            yield pcm


class KokoroTTS(tts.TTS):
    """The speech engine Marvi speaks with."""

    def __init__(self, *, voice: str = KOKORO_DEFAULT_VOICE) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=24_000,
            num_channels=1,
        )
        self._engine = _KokoroEngine.shared(voice)

    @property
    def model(self) -> str:
        return "kokoro-82M"

    @property
    def provider(self) -> str:
        return "hexgrad"

    @property
    def voices(self) -> list[str]:
        return self._engine.voices

    def prewarm(self) -> None:
        self._engine.load()

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> _WholeUtteranceStream:
        return _WholeUtteranceStream(tts=self, input_text=text, conn_options=conn_options)

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> _ClauseStream:
        return _ClauseStream(tts=self, conn_options=conn_options)


class _WholeUtteranceStream(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        # `stream=False`: this path synthesises one whole utterance. A
        # streaming emitter refuses every push until a segment is opened, and
        # this one never opened one -- so it produced no audio at all, and the
        # refusal was logged inside the emitter's own task where nothing was
        # watching.
        output_emitter.initialize(
            request_id=str(uuid.uuid4()), sample_rate=24_000, num_channels=1,
            mime_type="audio/pcm", frame_size_ms=20, stream=False,
        )
        stop = threading.Event()
        queue: asyncio.Queue[bytes | BaseException | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        engine = self._tts._engine

        def produce() -> None:
            try:
                for chunk in engine.synthesize(self._input_text, stop):
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
            except BaseException as exc:
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        worker = threading.Thread(target=produce, daemon=True)
        worker.start()
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, BaseException):
                    raise item
                output_emitter.push(item)
        finally:
            stop.set()
            await asyncio.to_thread(worker.join)


#: Punctuation that ends something worth speaking. A clause is enough: waiting
#: for a full stop means the first sound of a two-sentence reply arrives after
#: the model has written both.
_CLAUSE_END = ".!?…\n"

#: Below this, a fragment is not worth synthesising on its own -- "Yes" spoken
#: alone and then "it is" spoken alone sounds like two answers. Small enough
#: that a short reply is not held back waiting for words that never come.
MIN_SPEAKABLE = 4

#: How much audio to bank before the first word is heard, in seconds.
#:
#: The engine runs near real time on a good card and below it on a busy one,
#: and a producer even slightly behind the player empties it -- heard as a reply
#: arriving word, gap, word. This is the slack that absorbs that.
#:
#: Tunable because the right value is a property of the machine, not of Marvi:
#: a card that generates faster than real time needs none of this, and one that
#: does not needs more than is worth waiting for.
LEAD_SECONDS = float(os.environ.get("MARVI_TTS_LEAD_SECONDS", "0.6") or 0.6)
#: 24 kHz, mono, 32-bit float samples as the engine emits them.
#: 24 kHz, mono, int16 -- two bytes a sample. This said four, so the cushion
#: was twice the size it claimed and the realtime factor below reported half
#: the truth: a reply logged at 0.24x was really running at 0.48x.
_BYTES_PER_SECOND = 24_000 * 2
_LEAD_BYTES = int(_BYTES_PER_SECOND * max(0.0, LEAD_SECONDS))
#: However slow the engine, speaking starts by now. A cushion that takes
#: longer to fill than the gaps it exists to hide is not a cushion.
_LEAD_TIMEOUT = float(os.environ.get("MARVI_TTS_LEAD_TIMEOUT", "0.7") or 0.7)


def _next_clause(buffer: str) -> tuple[str, str]:
    """Split off the first speakable clause, if there is one.

    Returns `(clause, rest)`; an empty clause means nothing is ready yet.
    """
    for index, character in enumerate(buffer):
        if character in _CLAUSE_END and index + 1 >= MIN_SPEAKABLE:
            return buffer[: index + 1].strip(), buffer[index + 1 :]
    return "", buffer


class _ClauseStream(tts.SynthesizeStream):
    """Speak a reply while it is still being written.

    Tokens arrive from the LLM one at a time; audio for the first clause is
    generated and played while the rest of the sentence is still being
    produced. That is the whole difference between a voice that answers and a
    voice that pauses to compose.
    """

    def flush(self) -> None:
        """End the clause, not the reply.

        `SynthesizeStream.push_text` drops tokens once a stream has seen more
        than one segment, and `flush()` is what starts the second:

            if not self._mtc_text:
                if self._num_segments >= 1:
                    logger.warning("...deprecated...")
                    return

        `flush()` clears `_mtc_text`, so the first flush in a reply arms that
        branch and everything after it is discarded before this plugin sees a
        token. Heard as a long answer that speaks for a while and then stops
        mid-sentence, with one deprecation warning as the only trace.

        The remedy the warning gives -- a new stream per segment -- is not a
        plugin's to take: the session owns the stream's lifetime. So the stream
        is kept mid-segment instead. The flush sentinel still goes through, so
        the clause is still spoken; what does not happen is the counter moving
        on and the rest of the reply being thrown away.

        `_num_segments` is left alone deliberately. It is also what the emitter
        validates its segment count against, and resetting it trades a silent
        cut for `number of segments mismatch`.
        """
        super().flush()
        # Any non-empty value; `push_text` only tests it for emptiness.
        if not self._mtc_text:
            self._mtc_text = " "

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id=str(uuid.uuid4()),
            sample_rate=24_000,
            num_channels=1,
            mime_type="audio/pcm",
            frame_size_ms=20,
            stream=True,
        )
        buffer = ""
        # A streaming emitter refuses audio outside a segment, and says so by
        # raising inside its own task -- logged there, never where anyone was
        # looking. Marvi pushed every byte of every reply without opening one,
        # so she produced no audio at all and it read from outside as the model
        # having nothing to say.
        #
        # Opened lazily rather than up front: a segment that is started and
        # never filled still has to be ended, and the clause splitter cannot
        # promise there will be anything to say.
        open_segment = False
        began = time.monotonic()
        # Boxed so the release closure can add to it without another
        # nonlocal declaration.
        pushed = [0]
        # A cushion at the head of each reply.
        #
        # The room plays audio in real time. This engine produces it at around
        # one times real time on a good card and below that on a busy one, and
        # a producer that is even slightly behind its consumer runs the player
        # dry -- which is heard as a reply arriving word, gap, word.
        #
        # Holding back the first fraction of a second buys that much slack for
        # everything after it, at the cost of starting that much later. It
        # smooths jitter; it cannot manufacture throughput, so a long reply from
        # an engine genuinely below real time will still catch up with it.
        lead = _LEAD_BYTES
        held: list[bytes] = []
        released = False

        def release(chunk: bytes) -> None:
            nonlocal released
            pushed[0] += len(chunk)
            if released:
                output_emitter.push(chunk)
                return
            held.append(chunk)
            # Bounded by time as well as by size, and this is the important
            # half. Banking six hundred milliseconds of audio from an engine
            # running at a quarter of real time takes two and a half seconds --
            # so the cushion meant to smooth the reply was instead the longest
            # part of the wait before it started. Time to first byte went from
            # 232ms to 1801ms in the logs, which is the cushion, not the model.
            #
            # Whichever comes first: enough audio to be worth having, or long
            # enough that waiting is worse than the gaps it prevents.
            waited = time.monotonic() - began
            if sum(len(piece) for piece in held) < lead and waited < _LEAD_TIMEOUT:
                return
            for piece in held:
                output_emitter.push(piece)
            held.clear()
            released = True

        def drain() -> None:
            """Whatever is still held when the reply ends. It is the reply."""
            nonlocal released
            for piece in held:
                output_emitter.push(piece)
            held.clear()
            released = True

        async def speak(text: str) -> None:
            nonlocal open_segment
            if not text.strip():
                return
            if not open_segment:
                output_emitter.start_segment(segment_id=str(uuid.uuid4()))
                open_segment = True
            await _pump(self._tts._engine, text, release)

        def close_segment() -> None:
            nonlocal open_segment, released
            if open_segment:
                drain()
                output_emitter.end_segment()
                open_segment = False
            # The next segment is a new reply and buys its own cushion.
            released = False

        async for item in self._input_ch:
            if isinstance(item, self._FlushSentinel):
                # Say what is buffered, and keep the segment open.
                #
                # A flush mid-reply means "the sentence you have is finished",
                # not "the answer is over". Closing here opened a second
                # segment for the rest of the same reply -- the arrangement the
                # SDK deprecates -- and re-armed the cushion, so every sentence
                # after the first paid the lead again. One reply is one
                # segment, closed once, when the input actually ends.
                await speak(buffer)
                buffer = ""
                continue

            buffer += item
            while True:
                clause, buffer = _next_clause(buffer)
                if not clause:
                    break
                await speak(clause)

        await speak(buffer)
        close_segment()
        output_emitter.end_input()

        # The number that says whether the reply was heard in one piece.
        #
        # The room plays audio at exactly real time, so anything below 1.0
        # here means the engine produced it slower than the room consumed
        # it, the player ran dry, and the reply arrived word, gap, word.
        # Working that out the first time took an afternoon and a log full
        # of progress bars. It is one line now.
        spent = time.monotonic() - began
        produced = pushed[0] / _BYTES_PER_SECOND
        if spent > 0 and produced > 0:
            log.info(
                "tts: %.1fs of audio in %.1fs (%.2fx real time)%s",
                produced,
                spent,
                produced / spent,
                ""
                if produced / spent >= 1.0
                else "  <- below real time, expect gaps",
            )


async def _pump(engine: Any, text: str, release: Any) -> None:
    """Synthesise one clause, pushing audio as the model produces it.

    The engine is synchronous and CPU-bound, so it runs on a thread and hands
    chunks back through a queue. Each is pushed the moment it arrives rather
    than after the clause is finished -- the same reason the clause is spoken
    before the sentence is.
    """
    stop = threading.Event()
    queue: asyncio.Queue[bytes | BaseException | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def produce() -> None:
        try:
            for chunk in engine.synthesize(text, stop):
                loop.call_soon_threadsafe(queue.put_nowait, chunk)
        except BaseException as exc:
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    worker = threading.Thread(target=produce, daemon=True)
    worker.start()
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            release(item)
    finally:
        stop.set()
        await asyncio.to_thread(worker.join)
