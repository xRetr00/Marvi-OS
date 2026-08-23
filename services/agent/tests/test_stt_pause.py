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


# -- the recogniser that replaced the sidecar --------------------------------


def test_the_lookahead_is_a_setting_with_a_measured_default() -> None:
    """Two seconds measured 13.7% word errors and 0.8s measured 16.8%."""
    import os

    from marvi_agent.parakeet_stt import DEFAULT_LOOKAHEAD, lookahead_seconds

    assert DEFAULT_LOOKAHEAD == 2.0
    os.environ["MARVI_STT_LOOKAHEAD"] = "0.8"
    try:
        assert lookahead_seconds() == 0.8
    finally:
        del os.environ["MARVI_STT_LOOKAHEAD"]


def test_a_nonsense_lookahead_falls_back_rather_than_crashing(monkeypatch) -> None:
    from marvi_agent.parakeet_stt import DEFAULT_LOOKAHEAD, lookahead_seconds

    monkeypatch.setenv("MARVI_STT_LOOKAHEAD", "soon")
    assert lookahead_seconds() == DEFAULT_LOOKAHEAD

    # And clamped, because a ten second window is not a setting, it is a fault.
    monkeypatch.setenv("MARVI_STT_LOOKAHEAD", "60")
    assert lookahead_seconds() <= 4.0


def test_the_processor_is_the_default(monkeypatch) -> None:
    """It leaves the card to the speech synthesis, which is what ran out."""
    from marvi_agent.parakeet_stt import providers

    monkeypatch.delenv("MARVI_STT_DEVICE", raising=False)
    assert providers() == ["CPUExecutionProvider"]


def test_asking_for_the_card_asks_for_the_card(monkeypatch) -> None:
    from marvi_agent.parakeet_stt import providers

    monkeypatch.setenv("MARVI_STT_DEVICE", "cuda")
    assert providers()[0] == "CUDAExecutionProvider"


def test_the_agent_reads_where_the_installer_writes_the_recogniser() -> None:
    """Drift here means the Agent downloads its own copy, or hears nothing."""
    from pathlib import Path

    from marvi_agent.parakeet_stt import PARAKEET_ROOT

    root = Path(__file__).resolve().parents[3]
    catalog = (
        root / "services" / "gateway" / "src" / "marvi_gateway" / "setup" / "catalog.py"
    ).read_text(encoding="utf-8")

    assert 'install_to="models/stt/parakeet-tdt-0.6b-v3-onnx"' in catalog
    assert PARAKEET_ROOT.as_posix().endswith("models/stt/parakeet-tdt-0.6b-v3-onnx")
