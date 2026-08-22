"""The recogniser sits out while Marvi speaks.

Both models run on one card, and they competed hardest at the worst moment:
synthesis already runs close to real time, and below real time the room runs out
of audio and the reply arrives in pieces.

Interruption is detected by the VAD rather than by the recogniser -- LiveKit's
documentation is explicit that "the session's bundled VAD continues to handle
interruption detection" -- so pausing recognition does not cost barge-in. What
it could cost is the words somebody interrupts *with*, because by the time the
VAD stops the reply they have been talking for a moment. That is what these
pin down.
"""

from __future__ import annotations

from marvi_agent.voice_models import NemotronStream

SECOND = b"\x00\x01" * 16_000  # 16 kHz mono int16


def stream() -> NemotronStream:
    made = NemotronStream.__new__(NemotronStream)
    made._transcribing = True
    from collections import deque

    made._held = deque()
    return made


def test_it_transcribes_by_default() -> None:
    assert stream()._transcribing is True


def test_pausing_and_resuming_flips_it() -> None:
    live = stream()

    live.set_transcribing(False)
    assert live._transcribing is False

    live.set_transcribing(True)
    assert live._transcribing is True


def test_audio_held_during_a_pause_survives_the_resume() -> None:
    """The point of the whole buffer: an interruption keeps its first words."""
    live = stream()
    live.set_transcribing(False)
    live._held.append(SECOND)

    live.set_transcribing(True)

    assert len(live._held) == 1, "the backlog is flushed by the next frame, not dropped"


def test_pausing_drops_what_was_already_recognised() -> None:
    """Audio from before Marvi started speaking has been through the recogniser
    already; replaying it would repeat the sentence that caused the reply."""
    live = stream()
    live._held.append(SECOND)

    live.set_transcribing(False)

    assert not live._held


def test_the_hold_is_short_enough_not_to_be_mostly_echo() -> None:
    """Audio captured while Marvi speaks is mostly Marvi.

    A long hold flushes seconds of her own voice into the recogniser the moment
    she stops -- a spike of work at the worst possible time, spent transcribing
    words nobody said to her. The VAD notices an interruption within about a
    quarter of a second, so the onset is all that needs keeping.
    """
    assert NemotronStream._HOLD_SECONDS <= 1.0


def test_seconds_held_is_measured_in_the_right_units() -> None:
    """16 kHz mono int16 is two bytes a sample. Getting this wrong is how the
    TTS cushion ended up twice the size it claimed."""
    live = stream()
    live._held.append(SECOND)

    assert abs(live._buffered() - 1.0) < 0.01
