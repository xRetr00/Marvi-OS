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

import pytest

from marvi_agent.voice_models import VibeVoiceTTS


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


def tts_with(fake: FakeEngine) -> VibeVoiceTTS:
    engine = VibeVoiceTTS.__new__(VibeVoiceTTS)
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
    """"Yes." has no clause boundary to wait for and must not be held back."""
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
