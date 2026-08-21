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

from marvi_agent import wakeword
from marvi_agent.wakeword import DEFAULT_MODEL, WakeGate


@pytest.fixture(autouse=True)
def no_live_gateway(monkeypatch):
    """Settings come from the Gateway now, and a test must not ask a real one.

    Without this the suite passed or failed depending on whether Marvi was
    running on the machine and what its wake word was set to -- which is a test
    of the developer's desktop, not of the code.
    """
    monkeypatch.setattr(wakeword, "_gateway_settings", dict)


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


def test_the_wake_word_opens_a_conversation_and_it_stays_open() -> None:
    """A wake word starts a conversation. It is not a password on every turn.

    There were two gates and both were wrong. The acoustic one closed itself
    after thirty seconds, so a pause longer than that ended the conversation
    mid-thought. The other lived in the agent and dropped any turn whose
    transcript did not contain "marvi" -- silently, with nothing logged -- so
    asking a question after being greeted did nothing at all.
    """
    g = gate()
    session = FakeSession()
    g._session = session

    g._listen(reason="heard her name")

    assert g.awake
    assert session.input.audio_enabled is True

    # Time passing does not end it. Only `close` does.
    g._awake_until = 0.0 if hasattr(g, "_awake_until") else None
    assert g.awake, "a conversation must not expire on a timer"


def test_only_an_explicit_close_ends_it() -> None:
    g = gate()
    session = FakeSession()
    g._session = session
    g._listen(reason="test")

    g.close()

    assert not g.awake
    assert session.input.audio_enabled is False


def test_closing_twice_is_harmless() -> None:
    """The model may say goodbye and the user may hang up at the same moment."""
    g = gate()
    g._session = FakeSession()
    g._listen(reason="test")

    g.close()
    g.close()

    assert not g.awake


def test_hearing_her_name_again_mid_conversation_changes_nothing() -> None:
    """Saying "Marvi" inside an open conversation is just a word."""
    g = gate()
    session = FakeSession()
    g._session = session
    g._listen(reason="first")
    session.input.history.clear()

    g._listen(reason="second")

    assert g.awake
    assert session.input.history == [], "the session must not be re-opened"


def test_she_starts_deaf_and_wakes_on_her_name() -> None:
    g = gate()
    session = FakeSession()
    g._session = session
    session.input.set_audio_enabled(False)

    assert not g.awake

    g._listen(reason="test")

    assert g.awake
    assert session.input.audio_enabled is True








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


# -- the window --------------------------------------------------------------


def test_the_model_needs_a_whole_window_not_a_frame() -> None:
    """The bug that made the wake word impossible.

    `predict` is stateless and scores a complete window: "~2 seconds of 16 kHz
    audio is recommended (yields exactly 16 embeddings for the classifier).
    Shorter chunks that lack enough data return zero scores."

    Frames arriving from the room are about 10 ms, and each was being handed to
    `predict` on its own -- so every call took the "not enough data" path and
    returned exactly 0.0. It looked like a model correctly ignoring noise.

    Exactly 0.0 from a short chunk versus a real number from a full window is
    what tells those two apart.
    """
    from marvi_agent.wakeword import HOP_SAMPLES, WINDOW_SAMPLES

    model = gate()._model
    speechlike = np.random.default_rng(7).normal(0, 2000, WINDOW_SAMPLES).astype(np.int16)

    short = model.predict(speechlike[:HOP_SAMPLES])
    full = model.predict(speechlike)

    assert short["marvi"] == 0.0, "a short chunk cannot be scored at all"
    assert full["marvi"] != 0.0, "a full window must produce a real score"


def test_the_window_is_two_seconds_at_the_rate_the_model_wants() -> None:
    from marvi_agent.wakeword import SAMPLE_RATE, WINDOW_SAMPLES

    assert SAMPLE_RATE == 16_000
    assert WINDOW_SAMPLES == SAMPLE_RATE * 2


def test_the_hop_is_short_enough_to_catch_a_word() -> None:
    """The window slides by this much between scores.

    A spoken "Marvi" lasts a few hundred milliseconds; a hop near the window
    length would step straight over it.
    """
    from marvi_agent.wakeword import HOP_SAMPLES, SAMPLE_RATE, WINDOW_SAMPLES

    assert HOP_SAMPLES <= SAMPLE_RATE // 4
    assert HOP_SAMPLES < WINDOW_SAMPLES // 4


def test_a_full_window_of_silence_still_does_not_wake_her() -> None:
    """Now that windows are scored properly, silence has a real score.

    It is no longer the degenerate 0.0 of a chunk too short to evaluate, so
    this is the first time this assertion has meant anything.
    """
    from marvi_agent.wakeword import WINDOW_SAMPLES

    scored = gate()._model.predict(np.zeros(WINDOW_SAMPLES, dtype=np.int16))

    assert 0.0 < scored["marvi"] < 0.5


# -- where the setting comes from --------------------------------------------


def test_the_gateway_setting_wins_over_the_environment(monkeypatch) -> None:
    """The switch in Settings has to reach a process that cannot see it.

    The Agent runs separately and its environment is fixed when the desktop
    spawns it, so turning the wake word off in the UI changed a file this
    process never read. It armed anyway, muted the session's audio input, and
    the microphone went to a session that was not listening: no speech, no
    transcript, and nothing to say why.
    """
    monkeypatch.setenv("MARVI_WAKE_WORD", "true")
    monkeypatch.setattr(wakeword, "_gateway_settings", lambda: {"enabled": False})

    assert WakeGate.from_env() is None


def test_the_gateway_threshold_is_used(monkeypatch) -> None:
    monkeypatch.setattr(
        wakeword, "_gateway_settings", lambda: {"enabled": True, "threshold": 0.8}
    )

    gate = WakeGate.from_env()

    assert gate is not None
    assert gate.threshold == 0.8


def test_an_unreachable_gateway_falls_back_to_the_environment(monkeypatch) -> None:
    """A network blip must not leave Marvi permanently deaf."""
    monkeypatch.setattr(wakeword, "_gateway_settings", dict)
    monkeypatch.setenv("MARVI_WAKE_WORD", "true")
    monkeypatch.setenv("MARVI_WAKE_THRESHOLD", "0.6")

    gate = WakeGate.from_env()

    assert gate is not None
    assert gate.threshold == 0.6
