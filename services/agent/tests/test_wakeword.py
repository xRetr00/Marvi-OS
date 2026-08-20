"""The gate decides whether Marvi answers at all, so it is tested on both
directions of failure: staying deaf when she was addressed, and waking up when
she was not.

The model itself is real here. It is 97 KB and ships in the repo, so there is
no reason to assert against a mock of it -- and the thing most worth knowing
about this model is a property of the weights, not of the code: an earlier
version scored ~0.79 on an empty room, which made it useless. That is a
regression a mock could never catch.
"""

from __future__ import annotations

import numpy as np
import pytest

from marvi_agent.wakeword import DEFAULT_MODEL, WakeGate


class FakeInput:
    def __init__(self) -> None:
        self.audio_enabled = True
        self.history: list[bool] = []

    def set_audio_enabled(self, enabled: bool) -> None:
        self.audio_enabled = enabled
        self.history.append(enabled)


class FakeSession:
    def __init__(self) -> None:
        self.input = FakeInput()


def gate() -> WakeGate:
    return WakeGate(model_path=DEFAULT_MODEL, threshold=0.5, window=30.0)


def test_the_model_ships_with_the_repo() -> None:
    """No download stands between a fresh install and Marvi hearing her name."""
    assert DEFAULT_MODEL.is_file()
    assert DEFAULT_MODEL.stat().st_size > 1000


def test_an_empty_room_is_not_her_name() -> None:
    """The retrain's whole purpose.

    The previous model scored ~0.79 on silence -- the same band as a real
    "marvi" -- so it would have woken on an empty room. If this ever climbs
    back above the threshold the wake word is decorative.
    """
    scored = gate()._model.predict(np.zeros(16_000, dtype=np.int16))

    assert max(scored.values()) < 0.5


def test_room_noise_is_not_her_name() -> None:
    generator = np.random.default_rng(1234)
    noise = generator.normal(0, 800, 16_000).astype(np.int16)

    scored = gate()._model.predict(noise)

    assert max(scored.values()) < 0.5


def test_she_starts_deaf_and_wakes_on_her_name() -> None:
    g = gate()
    session = FakeSession()
    g._session = session
    session.input.set_audio_enabled(False)

    assert not g.awake

    g._listen(reason="test")

    assert g.awake
    assert session.input.audio_enabled is True


def test_the_window_closes_again() -> None:
    g = WakeGate(model_path=DEFAULT_MODEL, threshold=0.5, window=0.0)
    session = FakeSession()
    g._session = session

    g._listen(reason="test")

    # A zero-length window is already over, which is what the expiry loop
    # checks each second.
    assert not g.awake
    g._sleep()
    assert session.input.audio_enabled is False


def test_being_spoken_to_holds_the_window_open() -> None:
    g = gate()
    g._session = FakeSession()
    g._listen(reason="test")
    first = g._awake_until

    g.extend()

    assert g._awake_until >= first


def test_extending_does_not_wake_her_by_itself() -> None:
    """`extend` runs on every transcript, and transcripts exist while asleep.

    If it woke her, anything the room's STT happened to emit would open the
    gate -- which is the wake word not being a wake word.
    """
    g = gate()
    g._session = FakeSession()

    g.extend()

    assert not g.awake


def test_a_missing_model_leaves_her_listening_rather_than_deaf(monkeypatch, tmp_path) -> None:
    """Failing open, on purpose. Too talkative beats unreachable."""
    monkeypatch.setenv("MARVI_WAKE_MODEL", str(tmp_path / "absent.onnx"))

    assert WakeGate.from_env() is None


def test_the_wake_word_can_be_turned_off(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_WAKE_WORD", "false")

    assert WakeGate.from_env() is None


@pytest.mark.parametrize("value", ["0.8", "0.25"])
def test_the_threshold_comes_from_the_environment(monkeypatch, value: str) -> None:
    monkeypatch.setenv("MARVI_WAKE_THRESHOLD", value)

    configured = WakeGate.from_env()

    assert configured is not None
    assert configured.threshold == float(value)
