from __future__ import annotations

import asyncio
import base64
import copy
import json
import os
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
from livekit.agents import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions, stt, tts
from livekit.agents.types import NOT_GIVEN, NotGivenOr

APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Marvi-OS"
NEMOTRON_MODEL = (
    APP_DATA / "models/stt/nemotron-3.5/nemotron-3.5-asr-streaming-0.6b-onnx"
)
VIBEVOICE_ROOT = APP_DATA / "models/tts/vibevoice-realtime-0.5b"
DEFAULT_VOICE = "en-Carter_man"


class VoiceRuntimeError(RuntimeError):
    pass


class NemotronSTT(stt.STT):
    """Stateful native streaming STT backed by the Rust parakeet-rs sidecar."""

    def __init__(self, *, executable: Path, model_dir: Path = NEMOTRON_MODEL, language: str = "en-US"):
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True,
                interim_results=True,
                # `recognize()` raises here, and the default is True.
                # Nothing in the framework asks yet, so this is a claim
                # rather than a fault -- but a capability that is
                # declared and not implemented is a fault waiting for a
                # caller.
                offline_recognize=False,
            )
        )
        self._executable = executable
        self._model_dir = model_dir
        self._language = language
        self._streams: set[NemotronStream] = set()

    @property
    def model(self) -> str:
        return "nemotron-3.5-asr-streaming-0.6b"

    @property
    def provider(self) -> str:
        return "nvidia/parakeet-rs"

    async def _recognize_impl(self, *args: Any, **kwargs: Any) -> stt.SpeechEvent:
        raise NotImplementedError("NemotronSTT is streaming-only")

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> NemotronStream:
        stream = NemotronStream(stt=self, conn_options=conn_options)
        self._streams.add(stream)
        return stream

    async def aclose(self) -> None:
        await asyncio.gather(*(stream.aclose() for stream in tuple(self._streams)))
        self._streams.clear()


class NemotronStream(stt.RecognizeStream):
    def __init__(self, *, stt: NemotronSTT, conn_options: APIConnectOptions):
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=16_000)
        self._nemotron = stt
        self._process: asyncio.subprocess.Process | None = None
        self._transcript = ""
        # When the last word arrived, so silence can end the utterance.
        self._spoke_at = time.monotonic()
        # Until when late text belongs to an utterance already finished.
        self._settled_until = 0.0

    async def _send(self, payload: dict[str, str]) -> dict[str, Any]:
        if not self._process or not self._process.stdin or not self._process.stdout:
            raise VoiceRuntimeError("Nemotron runtime is not connected")
        self._process.stdin.write(json.dumps(payload, separators=(",", ":")).encode() + b"\n")
        await self._process.stdin.drain()
        line = await self._process.stdout.readline()
        if not line:
            stderr = b""
            if self._process.stderr:
                stderr = await self._process.stderr.read()
            raise VoiceRuntimeError(f"Nemotron runtime exited: {stderr.decode(errors='replace')}")
        response = json.loads(line)
        if not response.get("ok"):
            raise VoiceRuntimeError(response.get("error", "Nemotron inference failed"))
        return response

    #: Silence after speech before the utterance is called finished. Shorter
    #: than the session's endpointing window, so the final lands before the
    #: turn is given up on, and long enough not to cut a pause mid-sentence.
    _SILENCE = 0.6

    #: After finalising, text belonging to the utterance just closed is
    #: discarded for this long.
    #:
    #: The recogniser lags the audio -- it has lookahead, and it is fed frames
    #: that were captured before the silence was noticed -- so words keep
    #: arriving after the sentence is over. They used to open a *second* turn
    #: carrying the tail of the first:
    #:
    #:     stt: Hello Marvi, how you doing hello
    #:     stage: listening -> thinking
    #:     stt: , how you doing          <- the same sentence, again
    #:     stage: thinking -> listening  <- and the real turn is cancelled
    #:
    #: which is the loop: every answer interrupted by an echo of the question.
    _TAIL = 1.5

    def _emit(self, event_type: stt.SpeechEventType, text: str) -> None:
        self._event_ch.send_nowait(
            stt.SpeechEvent(
                type=event_type,
                request_id=str(uuid.uuid4()),
                alternatives=[stt.SpeechData(language=self._nemotron._language, text=text)],
            )
        )

    async def _run(self) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = await asyncio.create_subprocess_exec(
            str(self._nemotron._executable),
            str(self._nemotron._model_dir),
            self._nemotron._language,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=flags,
        )
        ready = await self._process.stdout.readline() if self._process.stdout else b""
        if not ready or not json.loads(ready).get("ok"):
            raise VoiceRuntimeError("Nemotron runtime failed to initialize")

        try:
            async for item in self._input_ch:
                if isinstance(item, self._FlushSentinel):
                    response = await self._send({"op": "flush"})
                    self._transcript += response.get("text", "")
                    if self._transcript.strip():
                        self._emit(stt.SpeechEventType.FINAL_TRANSCRIPT, self._transcript.strip())
                    self._transcript = ""
                    self._settled_until = time.monotonic() + self._TAIL
                    # The runtime keeps decoder state across `audio` calls --
                    # that is what makes it incremental -- so ending an
                    # utterance here without clearing it leaves the next one
                    # continuing the last. It shows up as a transcript that
                    # repeats what was already said:
                    #
                    #   Are you here?  Are you here?
                    await self._send({"op": "reset"})
                    continue

                pcm = bytes(item.data)
                response = await self._send(
                    {"op": "audio", "pcm16": base64.b64encode(pcm).decode("ascii")}
                )
                delta = response.get("text", "")
                if delta and time.monotonic() < self._settled_until:
                    # The tail of a sentence already answered. Dropping it is
                    # the difference between a conversation and a loop.
                    continue
                if delta:
                    self._transcript += delta
                    self._spoke_at = time.monotonic()
                    self._emit(stt.SpeechEventType.INTERIM_TRANSCRIPT, self._transcript.strip())
                elif self._transcript.strip() and (
                    time.monotonic() - self._spoke_at >= self._SILENCE
                ):
                    # Finality decided here, because nothing else decides it.
                    #
                    # A streaming STT is expected to say when an utterance is
                    # over; this one only did so on an explicit flush, and
                    # LiveKit never flushes an STT stream -- it flushes VAD and
                    # waits for the recogniser to declare a final of its own.
                    # So the transcript grew forever as interim results:
                    #
                    #   stt (partial): Hello Marvel, how you doing?  Are you here?
                    #
                    # perfectly recognised, and never acted on, because as far
                    # as the session was concerned the sentence had not ended.
                    #
                    # Audio keeps arriving during silence, so this is checked on
                    # the frames that carry none rather than on a timer.
                    self._emit(stt.SpeechEventType.FINAL_TRANSCRIPT, self._transcript.strip())
                    self._transcript = ""
                    self._settled_until = time.monotonic() + self._TAIL
                    # The runtime keeps decoder state across audio calls, so an
                    # utterance that ends without clearing it leaves the next one
                    # continuing the last.
                    await self._send({"op": "reset"})
        finally:
            if self._process.returncode is None:
                self._process.terminate()
                await self._process.wait()


class _VibeVoiceEngine:
    """Minimal adapter around Microsoft's official streaming inference classes."""

    sample_rate = 24_000

    def __init__(self, model_dir: Path, voices_dir: Path, voice: str, inference_steps: int):
        self.model_dir = model_dir
        self.voices_dir = voices_dir
        self.voice = voice
        self.inference_steps = inference_steps
        self._loaded = False

    @property
    def voices(self) -> list[str]:
        return sorted(path.stem for path in self.voices_dir.glob("*.pt"))

    def load(self) -> None:
        if self._loaded:
            return
        import torch
        from vibevoice.modular.modeling_vibevoice_streaming_inference import (
            VibeVoiceStreamingForConditionalGenerationInference,
        )
        from vibevoice.processor.vibevoice_streaming_processor import VibeVoiceStreamingProcessor

        if not torch.cuda.is_available():
            raise VoiceRuntimeError("VibeVoice requires the configured CUDA PyTorch runtime")
        if self.voice not in self.voices:
            raise VoiceRuntimeError(f"Unknown VibeVoice preset {self.voice!r}")

        self._torch = torch
        self._processor = VibeVoiceStreamingProcessor.from_pretrained(str(self.model_dir))
        try:
            self._model = VibeVoiceStreamingForConditionalGenerationInference.from_pretrained(
                str(self.model_dir), torch_dtype=torch.bfloat16, device_map="cuda",
                attn_implementation="flash_attention_2",
            )
        except Exception:
            self._model = VibeVoiceStreamingForConditionalGenerationInference.from_pretrained(
                str(self.model_dir), torch_dtype=torch.bfloat16, device_map="cuda",
                attn_implementation="sdpa",
            )
        self._model.eval()
        self._model.set_ddpm_inference_steps(num_steps=self.inference_steps)
        # `weights_only=False`, deliberately, and this is the whole reason
        # voice failed to speak on PyTorch 2.6+:
        #
        #   _pickle.UnpicklingError: Weights only load failed ...
        #   Can only SETITEMS for dict, collections.OrderedDict,
        #   collections.Counter, but got BaseModelOutputWithPast
        #
        # 2.6 flipped the default to True. Allowlisting the classes is not
        # enough -- the safe unpickler refuses SETITEMS on any dict subclass it
        # does not know, and a speaker prompt is exactly that.
        #
        # What is being trusted: these `.pt` files are sparse-checked-out from
        # Microsoft's VibeVoice repository at a *pinned commit*, so their
        # contents are fixed by that SHA. It is the same trust already placed
        # in the model weights sitting beside them -- not a new exposure, and
        # not a file from anywhere a user or a provider can reach.
        self._prompt = torch.load(
            self.voices_dir / f"{self.voice}.pt", map_location="cuda", weights_only=False
        )
        self._loaded = True

    def synthesize(self, text: str, stop: threading.Event) -> Iterator[bytes]:
        self.load()
        from vibevoice.modular.streamer import AudioStreamer

        inputs = self._processor.process_input_with_cached_prompt(
            text=text.strip().replace("\u2019", "'"), cached_prompt=self._prompt,
            padding=True, return_tensors="pt", return_attention_mask=True,
        )
        inputs = {key: value.to("cuda") if hasattr(value, "to") else value for key, value in inputs.items()}
        streamer = AudioStreamer(batch_size=1, stop_signal=None, timeout=None)
        errors: list[BaseException] = []

        def generate() -> None:
            try:
                self._model.generate(
                    **inputs, max_new_tokens=None, cfg_scale=1.5,
                    tokenizer=self._processor.tokenizer,
                    generation_config={"do_sample": False}, audio_streamer=streamer,
                    stop_check_fn=stop.is_set, verbose=False, refresh_negative=True,
                    # VibeVoice draws a tqdm bar unless told not to, and
                    # `verbose=False` does not cover it. It writes a line per
                    # generation step to stderr, which the desktop reads over a
                    # pipe and keeps -- three hundred lines and a megabyte of
                    # agent.log for one spoken reply, with the write happening
                    # inside the loop that is already struggling to keep up with
                    # realtime. It also buries every line worth reading.
                    show_progress_bar=False,
                    all_prefilled_outputs=copy.deepcopy(self._prompt),
                )
            except BaseException as exc:
                errors.append(exc)
                streamer.end()

        worker = threading.Thread(target=generate, daemon=True)
        worker.start()
        try:
            for chunk in streamer.get_stream(0):
                if stop.is_set():
                    break
                audio = chunk.detach().cpu().float().numpy().reshape(-1)
                peak = float(np.max(np.abs(audio))) if audio.size else 0.0
                if peak > 1.0:
                    audio /= peak
                yield (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()
        finally:
            stop.set()
            streamer.end()
            worker.join()
        if errors:
            raise errors[0]


class VibeVoiceTTS(tts.TTS):
    def __init__(self, *, root: Path = VIBEVOICE_ROOT, voice: str = DEFAULT_VOICE, inference_steps: int = 3):
        super().__init__(
            # Streaming, natively. It used to declare False and be wrapped in
            # LiveKit's StreamAdapter, which batches tokens into sentences of
            # at least twelve characters before synthesising anything -- so
            # "Yes." waited for more words that were never coming, and every
            # reply paid that delay before its first sound.
            #
            # The model itself takes a whole utterance, not tokens, so some
            # batching is unavoidable; owning it means the first clause can be
            # spoken as soon as it is one.
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=24_000,
            num_channels=1,
        )
        self._engine = _VibeVoiceEngine(root / "model", root / "voices", voice, inference_steps)

    @property
    def model(self) -> str:
        return "VibeVoice-Realtime-0.5B"

    @property
    def provider(self) -> str:
        return "microsoft"

    @property
    def voices(self) -> list[str]:
        return self._engine.voices

    def prewarm(self) -> None:
        self._engine.load()

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> _VibeVoiceChunkedStream:
        return _VibeVoiceChunkedStream(tts=self, input_text=text, conn_options=conn_options)

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> _VibeVoiceSynthesizeStream:
        return _VibeVoiceSynthesizeStream(tts=self, conn_options=conn_options)


class _VibeVoiceChunkedStream(tts.ChunkedStream):
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
_LEAD_BYTES = int(24_000 * 4 * max(0.0, LEAD_SECONDS))


def _next_clause(buffer: str) -> tuple[str, str]:
    """Split off the first speakable clause, if there is one.

    Returns `(clause, rest)`; an empty clause means nothing is ready yet.
    """
    for index, character in enumerate(buffer):
        if character in _CLAUSE_END and index + 1 >= MIN_SPEAKABLE:
            return buffer[: index + 1].strip(), buffer[index + 1 :]
    return "", buffer


class _VibeVoiceSynthesizeStream(tts.SynthesizeStream):
    """Speak a reply while it is still being written.

    Tokens arrive from the LLM one at a time; audio for the first clause is
    generated and played while the rest of the sentence is still being
    produced. That is the whole difference between a voice that answers and a
    voice that pauses to compose.
    """

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
            if released:
                output_emitter.push(chunk)
                return
            held.append(chunk)
            if sum(len(piece) for piece in held) < lead:
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
                # End of a segment: whatever is left is a clause of its own,
                # however short. Holding it back would drop the last words.
                await speak(buffer)
                buffer = ""
                close_segment()
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
