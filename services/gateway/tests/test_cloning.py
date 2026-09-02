"""Voices learned from a recording.

The rules worth pinning are the refusals. A cloning page that accepts anything
and fails inside a sidecar reports "TTS died" for a file that was never going
to work, so every refusal here is one a person can act on.
"""

from __future__ import annotations

import io
import math
import struct
import wave

import pytest

from marvi_gateway import cloning, voices


@pytest.fixture(autouse=True)
def _elsewhere(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVI_INSTALL_ROOT", str(tmp_path))
    voices.catalog.cache_clear()
    yield
    voices.catalog.cache_clear()


def recording(seconds: float, rate: int = 24_000, width: int = 2) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as sink:
        sink.setnchannels(1)
        sink.setsampwidth(width)
        sink.setframerate(rate)
        frames = int(rate * seconds)
        if width == 2:
            sink.writeframes(
                b"".join(struct.pack("<h", int(8000 * math.sin(i / 20))) for i in range(frames))
            )
        else:
            sink.writeframes(bytes(frames * width))
    return buffer.getvalue()


def test_only_cloning_engines_are_offered() -> None:
    assert cloning.engines() == ["cutetts-distill", "voxtream2"]


def test_kokoro_is_refused_by_name() -> None:
    # It has a fixed bank and takes no reference audio at all, so this is not
    # a limit of the feature but of the engine, and it should say so.
    with pytest.raises(cloning.CloneError, match="cannot speak in a cloned voice"):
        cloning.add("kokoro", "Nope", recording(5))


@pytest.mark.parametrize(
    ("audio", "complaint"),
    [
        (recording(0.3), "at least"),
        (recording(90), "the most usable"),
        (recording(5, rate=4_000), "minimum"),
        (recording(5, width=1), "16-bit"),
        (b"this is not a wav", "not a WAV"),
    ],
    # Named, because pytest builds ids out of the parameters and a WAV as an
    # id is a megabyte of escaped bytes in the test name -- long enough that
    # the run failed on the environment-variable length limit.
    ids=["too-short", "too-long", "too-low-a-rate", "not-16-bit", "not-a-wav"],
)
def test_unusable_recordings_say_why(audio: bytes, complaint: str) -> None:
    with pytest.raises(cloning.CloneError, match=complaint):
        cloning.add("cutetts-distill", "Bad", audio)


def test_a_recording_becomes_a_voice_in_the_picker() -> None:
    clone = cloning.add("cutetts-distill", "My Voice", recording(6))
    assert clone.id == "my-voice"
    assert cloning.path("cutetts-distill", clone.id).is_file()
    offered = voices.installed("cutetts-distill")
    assert [voice.id for voice in offered] == ["cute-reference", "my-voice"]
    assert offered[-1].cloned is True


def test_a_clone_belongs_to_one_engine() -> None:
    # The same recording through two engines is two different voices, and
    # neither should appear in the other's list.
    cloning.add("cutetts-distill", "Mine", recording(6))
    assert [v.id for v in voices.installed("voxtream2") if v.cloned] == []


def test_the_same_name_twice_does_not_overwrite() -> None:
    first = cloning.add("cutetts-distill", "Mine", recording(6))
    second = cloning.add("cutetts-distill", "Mine", recording(7))
    assert (first.id, second.id) == ("mine", "mine-2")
    assert cloning.path("cutetts-distill", first.id).is_file()


def test_removing_takes_the_recording_with_it() -> None:
    clone = cloning.add("cutetts-distill", "Mine", recording(6))
    where = cloning.path("cutetts-distill", clone.id)
    assert cloning.remove("cutetts-distill", clone.id) is True
    assert not where.exists()
    assert cloning.saved() == []
    # Removing it twice is not an error; it is already gone.
    assert cloning.remove("cutetts-distill", clone.id) is False


def test_a_clone_whose_file_vanished_is_not_offered() -> None:
    # Worse than absent in a picker: choosing it fails at synthesis time, in a
    # sidecar, with the voice already set.
    clone = cloning.add("cutetts-distill", "Mine", recording(6))
    cloning.path("cutetts-distill", clone.id).unlink()
    assert cloning.saved() == []
    assert [v.id for v in voices.installed("cutetts-distill")] == ["cute-reference"]
