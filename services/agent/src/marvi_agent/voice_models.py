from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
from livekit.agents import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions, tts

from . import sidecars

log = logging.getLogger("marvi.voice")

APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Marvi-OS"
NEMOTRON_MODEL = APP_DATA / "models/stt/nemotron-3.5/nemotron-3.5-asr-streaming-0.6b-onnx"
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
_SIDECARS: dict[tuple[str, str, int], _SidecarEngine] = {}

#: How long an interrupted synthesis gets to unwind before the sidecar is
#: killed.
#:
#: Short on purpose. `cancel` kills the process, and on Windows that is the
#: only thing that unblocks a worker thread sitting in `readline` on a sidecar
#: with nothing more to say -- so this window is a courtesy, not a policy. A
#: sidecar still producing audio finishes its sentence well inside a second and
#: keeps its warm model; one that has stopped talking is killed exactly as
#: before, so the worst case is the old behaviour.
_STOP_GRACE = 1.0
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


#: Kokoro's first letter is its language: `a` American and `b` British English,
#: then one letter per language. Its own convention, not a table invented here.
_G2P = {"a": "a", "b": "a", "e": "e", "f": "f", "h": "h", "i": "i", "j": "j", "p": "p", "z": "z"}


def g2p_code(voice: str) -> str:
    """Which grapheme-to-phoneme rules a voice needs.

    British English uses the American rules here because Kokoro's `b` voices
    are trained on them; the accent lives in the voice, not in the phonemiser.
    """
    return _G2P.get(voice[:1].lower(), "a") if voice else "a"


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

        # The grapheme-to-phoneme rules, from the voice rather than from a
        # constant. It was hardcoded to `a` -- American English -- which is
        # right until somebody installs a Spanish voice, at which point Spanish
        # text gets read with English rules and comes out as noise. Kokoro's
        # first letter is its language, so the voice already says which rules
        # it needs.
        self._pipeline = KPipeline(lang_code=g2p_code(self.voice), model=model, device=device)
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
        self._pipeline.voices[self.voice] = torch.load(path, map_location=device, weights_only=True)

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


def _tts_catalog() -> dict[str, dict[str, Any]]:
    path = Path(__file__).resolve().parents[4] / "config" / "tts-engines.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(item["id"]): item for item in raw.get("engines", ())}


def resolve_engine(engine: str) -> str:
    offered = _tts_catalog()
    if engine in offered:
        return engine
    if engine:
        log.warning("unknown TTS engine %r; using Kokoro", engine)
    return "kokoro"


def default_voice(engine: str) -> str:
    return str(_tts_catalog()[resolve_engine(engine)]["default_voice"])


class _SidecarEngine:
    """A persistent isolated upstream runtime speaking newline-delimited JSON.

    Each optional engine owns a separate uv environment. That is necessary,
    not decorative: CuteTTS and VoXtream pin stacks that differ from the Agent.
    Only PCM crosses this boundary, so choosing one cannot uninstall or replace
    Kokoro's dependencies.
    """

    sample_rate = 24_000

    def __init__(self, engine: str, voice: str) -> None:
        self.engine = resolve_engine(engine)
        spec = _tts_catalog()[self.engine]
        offered = {str(item["id"]) for item in spec.get("voices", ())}
        self.voice = voice if voice in offered else str(spec["default_voice"])
        self._process: subprocess.Popen[str] | None = None
        self._speaking = threading.Lock()
        #: The thread cleaning up after a barge-in, if one is running.
        self._recovering: threading.Thread | None = None
        self._recovering_lock = threading.Lock()

    @classmethod
    def shared(cls, engine: str, voice: str) -> _SidecarEngine:
        selected = resolve_engine(engine)
        spec = _tts_catalog()[selected]
        offered = {str(item["id"]) for item in spec.get("voices", ())}
        selected_voice = voice if voice in offered else str(spec["default_voice"])
        key = (selected, selected_voice, 0)
        with _ENGINE_LOCK:
            # Every other sidecar goes, and that is the whole point of the
            # cache being keyed rather than a single slot. A sidecar is a live
            # process holding a model in VRAM: switching engine three times
            # left three of them resident, and on a 12 GB card the third one
            # has nowhere to go. Nothing reclaimed them, because the key it was
            # no longer looked up under is not a key anything ever visits
            # again.
            #
            # Closed rather than dropped: letting the object fall out of the
            # dict leaves the process running with no handle to stop it.
            found = _SIDECARS.get(key)
            for name, other in list(_SIDECARS.items()):
                if name != key:
                    other.close()
            _SIDECARS.clear()
            if found is None:
                found = cls(selected, selected_voice)
                # Registered on creation rather than on start: a sidecar that
                # fails half way through starting still has a process to kill.
                sidecars.track(found)
            _SIDECARS[key] = found
            return found

    def _start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        spec = _tts_catalog()[self.engine]
        uv = shutil.which("uv")
        if not uv:
            raise VoiceRuntimeError("uv is required to start an optional TTS engine")
        repo = Path(__file__).resolve().parents[4]
        project = repo / str(spec["project"])
        command = [uv, "run", "--project", str(project), "python", "-m", str(spec["module"])]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        environment = os.environ.copy()
        # The Agent itself runs inside a uv environment. Passing its
        # VIRTUAL_ENV into another `uv run --project` makes uv warn on every
        # optional-engine start and can make future uv versions select the
        # wrong environment. Each sidecar owns the project named above.
        environment.pop("VIRTUAL_ENV", None)
        self._process = subprocess.Popen(
            command,
            cwd=repo,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=flags,
            env=environment,
        )
        ready = self._read()
        if ready.get("event") != "ready":
            self.close()
            raise VoiceRuntimeError(str(ready.get("error") or f"{self.engine} did not start"))
        self.sample_rate = int(ready.get("sample_rate") or 24_000)
        if self.sample_rate != 24_000:
            self.close()
            raise VoiceRuntimeError(
                f"{self.engine} outputs {self.sample_rate} Hz; Marvi requires 24000 Hz PCM"
            )

    def _read(self) -> dict[str, Any]:
        # Held in a local for the whole call. `readline` blocks, `close` runs on
        # another thread and sets `self._process = None`, and reading the
        # attribute again afterwards found nothing there:
        #
        #   could not prewarm the speech models:
        #   'NoneType' object has no attribute 'poll'
        #
        # It happened when a session ended while prewarm was still waiting for
        # the sidecar's ready line. Prewarm then failed, so the models loaded
        # inside the first spoken turn instead -- which is what the 6.8-second
        # time-to-first-token spikes in the log are.
        process = self._process
        if process is None or process.stdout is None:
            raise VoiceRuntimeError(f"{self.engine} is not running")
        line = process.stdout.readline()
        if not line:
            raise VoiceRuntimeError(f"{self.engine} stopped unexpectedly ({process.poll()})")
        return json.loads(line)

    def load(self) -> None:
        self._start()

    def synthesize(self, text: str, stop: threading.Event) -> Iterator[bytes]:
        with self._speaking:
            # Whatever the last barge-in left behind, finished first.
            self._settled()
            self._start()
            process = self._process
            if process is None or process.stdin is None:
                raise VoiceRuntimeError(f"{self.engine} is not running")
            process.stdin.write(json.dumps({"text": text, "voice": self.voice}) + "\n")
            process.stdin.flush()
            while True:
                if stop.is_set():
                    # Drained, not killed.
                    #
                    # This used to `close()`, which taskkills the sidecar and
                    # everything under it. So every barge-in destroyed a
                    # process holding a model in VRAM, and the next sentence
                    # paid a full reload -- tens of seconds for CuteTTS or
                    # VoXtream. Interrupting an assistant is the most ordinary
                    # thing a person does to one; it should not be the most
                    # expensive.
                    #
                    # The upstream generation is left to finish and its audio
                    # thrown away. That costs a few hundred milliseconds of GPU
                    # nobody hears, and leaves a warm process for the next
                    # sentence. Only a sidecar that will not finish gets killed.
                    self._recover()
                    break
                message = self._read()
                event = message.get("event")
                if event == "chunk":
                    yield base64.b64decode(str(message["pcm"]))
                elif event == "done":
                    break
                elif event == "error":
                    raise VoiceRuntimeError(str(message.get("error") or "TTS sidecar failed"))

    #: How long to let an abandoned generation finish before giving up on it.
    #:
    #: This was `_STOP_GRACE`, one second, on the reasoning that draining for
    #: longer than the caller will wait means the process gets killed anyway.
    #: The two quantities are unrelated, and one second is not the cost of
    #: being wrong. A reply is abandoned mid-generation, so what is left to
    #: drain is most of a sentence -- five seconds of audio at the ~1.8x this
    #: engine runs at is nearly three seconds of work. One second of patience
    #: therefore killed the sidecar on essentially every barge-in, and a
    #: killed sidecar reloads its model: 37.7 s to 43.9 s for CuteTTS.
    #:
    #: The log has exactly that, in the reply after an interruption:
    #:
    #:     00:56:05  cutetts-distill did not finish after an interruption
    #:     00:57:04  tts: 10.1s of audio in 50.4s (0.20x real time;
    #:               engine 0.20x, 0.0s waiting for the model)
    #:
    #: Fifty seconds for ten seconds of speech, all of it the model loading
    #: again inside the reply. The comment above `synthesize` already says the
    #: right thing -- "interrupting an assistant is the most ordinary thing a
    #: person does to one; it should not be the most expensive" -- and this
    #: number was quietly undoing it.
    #:
    #: Fifteen seconds covers the longest reply this cap allows, and nothing
    #: waits on it: see `_drain`, which now runs on its own thread.
    DRAIN_TIMEOUT = 15.0

    def _drain(self) -> bool:
        """Read the rest of an abandoned response so the process stays usable.

        The protocol is a stream per request. Abandoning one mid-flight leaves
        chunks in the pipe that the *next* request would read as its own, so
        the choice is to finish reading this one or to throw the process away.
        Reading is far cheaper.
        """
        process = self._process
        if process is None or process.stdout is None:
            return False
        deadline = time.monotonic() + self.DRAIN_TIMEOUT
        while time.monotonic() < deadline:
            try:
                message = self._read()
            except VoiceRuntimeError:
                return False
            if message.get("event") in ("done", "error"):
                return True
        log.warning("%s did not finish after an interruption; restarting it", self.engine)
        return False

    def _recover(self) -> None:
        """Clean up after a barge-in without making the next reply pay for it.

        Both halves of this used to happen inline, on the thread that noticed
        the interruption, which is the thread the next sentence needs. So the
        person barged in, said their piece, and then waited out whichever of
        the two had been chosen for them -- a drain, or a whole model reload.

        Neither is urgent. The audio is already stopped; all that is left is
        to have a usable process by the time there is something to say. That
        is what the next `synthesize` waits on, and by then the user has
        spoken a sentence and the model has been reloading throughout it.
        """
        with self._recovering_lock:
            if self._recovering is not None and self._recovering.is_alive():
                return

            def work() -> None:
                if not self._drain():
                    self.close()
                    # Eagerly, not on next use. A reload that starts when the
                    # person begins their next sentence is mostly done by the
                    # time they finish it; one that starts when Marvi tries to
                    # answer is fifty seconds of silence.
                    with contextlib.suppress(Exception):
                        self._start()

            self._recovering = threading.Thread(
                target=work, name=f"marvi-tts-recover-{self.engine}", daemon=True
            )
            self._recovering.start()

    def _settled(self) -> None:
        """Wait for any recovery to finish. Called before using the process."""
        with self._recovering_lock:
            recovering = self._recovering
        if recovering is not None:
            recovering.join()

    def close(self) -> None:
        process, self._process = self._process, None
        # `uv run` is a wrapper around the runtime that holds the model, so
        # the whole tree goes. See `sidecars.kill_tree`.
        sidecars.kill_tree(process)
        sidecars.forget(self)

    def cancel(self) -> None:
        """Interrupt upstream generation; the next request starts a clean host."""
        self.close()


class SidecarTTS(KokoroTTS):
    def __init__(self, *, engine: str, voice: str) -> None:
        tts.TTS.__init__(
            self,
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=24_000,
            num_channels=1,
        )
        self.engine_id = resolve_engine(engine)
        self._engine = _SidecarEngine.shared(self.engine_id, voice)

    @property
    def model(self) -> str:
        return str(_tts_catalog()[self.engine_id]["model_id"])

    @property
    def provider(self) -> str:
        return "local"

    @property
    def voices(self) -> list[str]:
        return [str(item["id"]) for item in _tts_catalog()[self.engine_id].get("voices", ())]


def build_tts(engine: str = "kokoro", voice: str = "") -> KokoroTTS | SidecarTTS:
    selected = resolve_engine(engine)
    wanted_voice = voice or default_voice(selected)
    if selected == "kokoro":
        return KokoroTTS(voice=wanted_voice)
    return SidecarTTS(engine=selected, voice=wanted_voice)


class _WholeUtteranceStream(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        # `stream=False`: this path synthesises one whole utterance. A
        # streaming emitter refuses every push until a segment is opened, and
        # this one never opened one -- so it produced no audio at all, and the
        # refusal was logged inside the emitter's own task where nothing was
        # watching.
        output_emitter.initialize(
            request_id=str(uuid.uuid4()),
            sample_rate=24_000,
            num_channels=1,
            mime_type="audio/pcm",
            frame_size_ms=20,
            stream=False,
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
            # Given a moment to stop on its own before being killed. The worker
            # notices `stop` on its next chunk and drains the sidecar, which
            # keeps the process warm; `cancel` throws it away, and that is the
            # fallback rather than the routine path.
            await asyncio.to_thread(worker.join, _STOP_GRACE)
            cancel = getattr(engine, "cancel", None)
            if callable(cancel) and worker.is_alive():
                cancel()
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


#: Tool-call markup a model sometimes writes as prose instead of calling a tool.
#:
#: Seen in a real session: "The file is saved in my workspace at shreef.txt.
#: Let me check it's still there. <invoke name=..." -- and Marvi read the tag,
#: the parameter names and the file contents aloud, thirty-nine seconds of it.
#: Two separate faults, and this is only the second one: the tool did not run,
#: and then what should have been the tool call was spoken.
#:
#: Anthropic-style `<invoke>`, OpenAI-style `<tool_call>`, and the namespaced
#: variants of both.
_TOOL_MARKUP = re.compile(r"<\s*/?\s*(antml:)?(invoke|function_calls?|parameter|tool_call)\b", re.I)


def _speakable(text: str) -> tuple[str, bool]:
    """What is worth saying out loud, and whether markup started here.

    Everything before the markup is real speech and is kept; the markup and
    everything after it is machinery. The caller stops speaking for the rest of
    the reply rather than resuming after the tag, because what follows a tool
    call written as text is the arguments, and those are not sentences either.
    """
    match = _TOOL_MARKUP.search(text)
    if not match:
        return text, False
    return text[: match.start()].rstrip(), True


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
        #: Set when the model starts writing markup where speech should be.
        muted = False
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
            nonlocal open_segment, muted
            if muted:
                return
            text, markup = _speakable(text)
            if markup:
                # For the rest of this reply. A stream carries one reply, so
                # the flag clears with it; a stream that carried two would
                # silence the second, which is the safer half of a turn that
                # has already gone wrong.
                muted = True
                log.warning(
                    "tts: the model wrote a tool call as text instead of calling one; "
                    "not speaking the rest of this reply"
                )
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

        # Time spent waiting for the model to write the next words, kept apart
        # from time spent turning words into sound. See the log line below.
        # Measured as the gap between finishing one item and receiving the
        # next, rather than by taking the iteration apart: same number, and it
        # leaves the loop that carries every spoken word exactly as it was.
        idle = 0.0
        handed = time.monotonic()

        async for item in self._input_ch:
            idle += time.monotonic() - handed
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
                # Before the continue, or the synthesis just done would be
                # counted as time spent waiting for the model.
                handed = time.monotonic()
                continue

            buffer += item
            while True:
                clause, buffer = _next_clause(buffer)
                if not clause:
                    break
                await speak(clause)
            handed = time.monotonic()

        await speak(buffer)
        close_segment()
        output_emitter.end_input()

        # Whether the reply was heard in one piece -- and, when it was not,
        # which half of the pipeline to go after.
        #
        # The room plays audio at exactly real time, so below 1.0 overall means
        # the player ran dry and the reply arrived word, gap, word. That much
        # was right. What was wrong was the label: `began` is the start of the
        # *reply*, and this loop spends most of it waiting on `_input_ch` for
        # the LLM to write the next clause. A slow model was therefore reported
        # as a slow engine, under a line that starts with `tts:`.
        #
        # Live, that misread a whole conversation. Across four turns the
        # numbers moved together --
        #
        #     llm ttft 1921ms  tts ttfb  627ms   9.9s of audio in  6.8s (1.46x)
        #     llm ttft 3520ms  tts ttfb 2628ms   2.6s of audio in  6.4s (0.40x)
        #     llm ttft 3550ms  tts ttfb 5242ms  14.7s of audio in 14.1s (1.04x)
        #     llm ttft 4094ms  tts ttfb 8854ms  14.2s of audio in 23.2s (0.61x)
        #
        # -- the "TTS rate" falling as the model's own latency climbed, on a
        # local engine whose speed had not changed at all. Two afternoons went
        # into the engine on the strength of that number.
        #
        # So both are reported: what the engine did with the time it had, and
        # how much of the reply was spent waiting for something to say.
        spent = time.monotonic() - began
        produced = pushed[0] / _BYTES_PER_SECOND
        working = max(spent - idle, 1e-6)
        if spent > 0 and produced > 0:
            log.info(
                "tts: %.1fs of audio in %.1fs (%.2fx real time; engine %.2fx, "
                "%.1fs waiting for the model)%s",
                produced,
                spent,
                produced / spent,
                produced / working,
                idle,
                ""
                if produced / spent >= 1.0
                else (
                    "  <- gaps, and the model is the slower half"
                    if idle > working
                    else "  <- gaps, and the engine is the slower half"
                ),
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
        await asyncio.to_thread(worker.join, _STOP_GRACE)
        cancel = getattr(engine, "cancel", None)
        if callable(cancel) and worker.is_alive():
            cancel()
            await asyncio.to_thread(worker.join)
