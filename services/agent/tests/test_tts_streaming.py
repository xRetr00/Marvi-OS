"""Does the TTS actually produce audio?

Everything about the streaming TTS looked right: it declared itself streaming,
it split clauses, it pushed bytes as the engine produced them. It emitted no
audio at all, because `AudioEmitter` in streaming mode refuses any push before
a segment is opened, and the refusal happens inside the emitter's own task --
logged there, not raised where anyone was looking.

From outside it looked exactly like the model having nothing to say: the
session went listening, thinking, and back to listening without a word.

So this asserts frames, not calls. A test that checks the adapter pushed bytes
would have passed throughout.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from marvi_agent.voice_models import KokoroTTS


class FakeEngine:
    """Stands in for VibeVoice: real PCM, none of the 0.5B model."""

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def load(self) -> None:
        return None

    @property
    def voices(self) -> list[str]:
        return ["test"]

    def synthesize(self, text: str, stop):
        self.spoken.append(text)
        # 24 kHz mono int16: a tenth of a second, in two chunks, so the test
        # covers more than a single push.
        yield b"\x00\x01" * 1200
        yield b"\x00\x01" * 1200


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


def tts_with(fake: FakeEngine) -> KokoroTTS:
    engine = KokoroTTS.__new__(KokoroTTS)
    # Build the base class without touching the model directory.
    from livekit.agents import tts as lk_tts

    lk_tts.TTS.__init__(
        engine,
        capabilities=lk_tts.TTSCapabilities(streaming=True),
        sample_rate=24_000,
        num_channels=1,
    )
    engine._engine = fake
    return engine


async def collect(stream) -> list:
    frames = []
    async for event in stream:
        frames.append(event)
    return frames


async def test_a_streamed_reply_produces_audio(engine) -> None:
    """The one that matters. Nothing downstream can recover from no frames."""
    speaker = tts_with(engine)
    stream = speaker.stream()

    stream.push_text("Hello there.")
    stream.end_input()

    frames = await collect(stream)
    await stream.aclose()

    assert frames, "the streaming TTS emitted no audio at all"
    assert sum(f.frame.samples_per_channel for f in frames) > 0


async def test_the_first_clause_is_spoken_before_the_sentence_is_finished(engine) -> None:
    """The whole point of streaming: audio for "Hello." while the rest is
    still being written. If the engine is only ever handed the whole reply,
    the first word waits for the last one."""
    speaker = tts_with(engine)
    stream = speaker.stream()

    for token in ("Hello", " there.", " How", " are", " you?"):
        stream.push_text(token)
    stream.end_input()

    await collect(stream)
    await stream.aclose()

    assert len(engine.spoken) >= 2, f"synthesised in one go: {engine.spoken}"
    assert engine.spoken[0] == "Hello there."


async def test_a_short_reply_is_still_spoken(engine) -> None:
    """ "Yes." has no clause boundary to wait for and must not be held back."""
    speaker = tts_with(engine)
    stream = speaker.stream()

    stream.push_text("Yes.")
    stream.end_input()

    frames = await collect(stream)
    await stream.aclose()

    assert frames, "a short reply produced no audio"


async def test_the_non_streaming_path_produces_audio_too(engine) -> None:
    """`synthesize()` is used for anything said outside a generated turn."""
    speaker = tts_with(engine)
    stream = speaker.synthesize("Hello there.")

    frames = await collect(stream)
    await stream.aclose()

    assert frames, "the chunked TTS emitted no audio at all"


# -- the cushion -------------------------------------------------------------


class LongEngine(FakeEngine):
    """Enough audio to pass the lead and keep going."""

    def synthesize(self, text: str, stop):
        self.spoken.append(text)
        for _ in range(40):
            yield b"\x00\x01" * 2400  # 0.05s of 24kHz float32 per chunk


def samples(frames) -> int:
    return sum(f.frame.samples_per_channel for f in frames)


async def test_the_cushion_delays_audio_without_losing_any() -> None:
    """Holding back the first fraction of a second is only acceptable if every
    byte still arrives. A buffer that drops its contents is worse than none."""
    engine = LongEngine()
    speaker = tts_with(engine)
    stream = speaker.stream()

    stream.push_text("Hello there.")
    stream.end_input()

    frames = await collect(stream)
    await stream.aclose()

    # 40 chunks of 2400 float32 samples: what the engine produced is what the
    # room hears, cushion or not.
    assert samples(frames) == 40 * 2400


async def test_a_reply_shorter_than_the_cushion_is_still_spoken(engine) -> None:
    """The whole reply fits inside the lead, so nothing ever crosses the
    threshold that releases it. It must be drained at the end regardless --
    otherwise "Yes." is silence."""
    speaker = tts_with(engine)
    stream = speaker.stream()

    stream.push_text("Yes.")
    stream.end_input()

    frames = await collect(stream)
    await stream.aclose()

    assert samples(frames) == 2 * 1200


async def test_a_flush_mid_reply_delivers_everything_before_it() -> None:
    """One stream carries one segment.

    LiveKit deprecated handling several in a single `SynthesizeStream` and drops
    the text of any after the first, so the cushion only ever has one reply to
    hold. What a flush must not do is strand what was already pushed.
    """
    engine = LongEngine()
    speaker = tts_with(engine)
    stream = speaker.stream()

    stream.push_text("Only this one.")
    stream.flush()
    stream.end_input()

    frames = await collect(stream)
    await stream.aclose()

    assert samples(frames) == 40 * 2400
    assert engine.spoken == ["Only this one."]


# -- the shattering ----------------------------------------------------------


def test_a_chunk_boundary_does_not_change_the_gain() -> None:
    """Speech that "comes out shattered or cut".

    Each buffer used to be divided by its own peak whenever that peak exceeded
    one. Per buffer: one peaking at 1.4 was scaled down and the next, peaking at
    0.9, was not, so the gain stepped at the boundary between them. A step in
    gain mid-waveform is a discontinuity, which is a click, and a click at every
    buffer boundary is speech that shatters.

    Nothing about where the model hands over a buffer means anything
    acoustically, so the same samples must come out the same however they were
    divided up.
    """
    import numpy as np

    from marvi_agent.voice_models import to_pcm

    # Overshoots in its first half and not its second -- exactly the case the
    # old code treated as two recordings needing different gain.
    loud = np.full(600, 1.4, dtype=np.float32)
    quiet = np.full(600, 0.9, dtype=np.float32)

    whole, _ = to_pcm(np.concatenate([loud, quiet]))
    split = to_pcm(loud)[0] + to_pcm(quiet)[0]

    assert whole == split, "the same audio differs depending on where it was cut"


def test_overshoot_is_counted_rather_than_hidden() -> None:
    """If the model really does overshoot often that is worth knowing, and
    worth fixing at the model rather than papering over per buffer."""
    import numpy as np

    from marvi_agent.voice_models import to_pcm

    _, over = to_pcm(np.array([0.5, 1.4, -1.9, 0.2], dtype=np.float32))

    assert over == 2


def test_audio_within_range_is_left_alone() -> None:
    import numpy as np

    from marvi_agent.voice_models import to_pcm

    pcm, over = to_pcm(np.array([1.0, -1.0, 0.0], dtype=np.float32))

    assert over == 0
    assert np.frombuffer(pcm, dtype=np.int16).tolist() == [32767, -32767, 0]


# -- the engine swap ---------------------------------------------------------


def test_a_voice_from_the_old_engine_does_not_kill_speech() -> None:
    """Every install that ran Marvi before carries one.

    `en-Carter_man` was a VibeVoice speaker prompt; Kokoro has never heard of
    it. Passing it through would raise on the first spoken turn of the first
    session after an update -- voice silently dead, for a reason nowhere near
    where anyone would look.
    """
    from marvi_agent.voice_models import KOKORO_DEFAULT_VOICE, resolve_voice

    assert resolve_voice("en-Carter_man") == KOKORO_DEFAULT_VOICE
    assert resolve_voice("") == KOKORO_DEFAULT_VOICE


def test_a_voice_the_engine_has_is_left_alone() -> None:
    from marvi_agent.voice_models import resolve_voice

    assert resolve_voice("bf_emma") == "bf_emma"


def test_the_two_services_offer_the_same_voices() -> None:
    """The picker writes what the engine reads. They are in different packages
    and different Python environments, so nothing but a test keeps them level.
    """
    import json
    from pathlib import Path

    from marvi_agent.voice_models import KOKORO_VOICES

    catalog = json.loads(
        (Path(__file__).resolve().parents[3] / "config" / "tts-engines.json").read_text(
            encoding="utf-8"
        )
    )
    kokoro = next(engine for engine in catalog["engines"] if engine["id"] == "kokoro")
    offered = {voice["id"] for voice in kokoro["voices"]}

    assert offered == set(KOKORO_VOICES), (
        f"only in the Gateway: {offered - set(KOKORO_VOICES)}; "
        f"only in the Agent: {set(KOKORO_VOICES) - offered}"
    )


def test_the_agent_reads_where_the_installer_writes() -> None:
    """Two files, one path, and nothing but this keeping them level.

    The installer puts Kokoro at `install_to`; the Agent reads `KOKORO_ROOT`.
    If they drift the Agent silently falls back to downloading its own copy --
    318MB fetched twice, and an offline machine that never speaks.
    """
    import json
    from pathlib import Path

    from marvi_agent.voice_models import KOKORO_ROOT

    root = Path(__file__).resolve().parents[3]
    catalog = (
        root / "services" / "gateway" / "src" / "marvi_gateway" / "setup" / "catalog.py"
    ).read_text(encoding="utf-8")

    assert 'install_to="models/tts/kokoro-82m"' in catalog
    assert KOKORO_ROOT.as_posix().endswith("models/tts/kokoro-82m")

    # And the download manifest points at the repository those files come from.
    manifest = json.loads((root / "config" / "voice-models.json").read_text(encoding="utf-8"))
    assert manifest["tts"]["id"] == "hexgrad/Kokoro-82M"
    assert manifest["tts"]["default_voice"] == "am_michael"


def test_every_offered_voice_is_actually_downloaded() -> None:
    """A voice in the picker that the installer never fetched is a voice that
    downloads itself mid-conversation, or fails to."""
    import json
    from pathlib import Path

    from marvi_agent.voice_models import KOKORO_VOICES

    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / "config" / "voice-models.json").read_text(encoding="utf-8"))
    fetched = {
        name.removeprefix("voices/").removesuffix(".pt")
        for name in manifest["tts"]["files"]
        if name.startswith("voices/")
    }

    assert set(KOKORO_VOICES) == fetched


async def test_a_reply_that_is_flushed_mid_way_is_still_spoken_whole(engine) -> None:
    """Long answers stop mid-sentence after speaking for a while.

    `SynthesizeStream.push_text` drops tokens once a stream has seen more than
    one segment, and `flush()` is what starts the second:

        if not self._mtc_text:
            if self._num_segments >= 1:
                logger.warning("...deprecated...")
                return

    If the session flushes between sentences and keeps pushing into the same
    stream, everything after the first flush is discarded before this plugin
    sees it. This asserts the words, not the calls: what matters is that the
    second half of the answer is spoken at all.
    """
    speaker = tts_with(engine)
    stream = speaker.stream()

    stream.push_text("First sentence here.")
    stream.flush()
    stream.push_text(" Second sentence here.")
    stream.end_input()

    await collect(stream)
    await stream.aclose()

    said = " ".join(engine.spoken)
    assert "First sentence" in said
    assert "Second sentence" in said, f"everything after the flush was dropped: {engine.spoken}"


async def test_cancelling_a_sidecar_pump_stops_blocked_generation() -> None:
    from marvi_agent.voice_models import _pump

    class BlockingEngine:
        def __init__(self) -> None:
            self.released = threading.Event()
            self.cancelled = False

        def synthesize(self, _text, _stop):
            self.released.wait(5)
            if False:
                yield b""

        def cancel(self) -> None:
            self.cancelled = True
            self.released.set()

    engine = BlockingEngine()
    task = asyncio.create_task(_pump(engine, "hello", lambda _chunk: None))
    await asyncio.sleep(0.02)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert engine.cancelled is True
