"""The Kyutai recogniser, and the guards around its end-of-turn signal.

`moshi` and a 2.3 GB checkpoint are not importable in a unit test, so the model
is a stand-in. What is worth pinning here is not the transcription -- the
benchmark measures that -- but the turn-taking logic, which is the only reason
this recogniser is carried at all and the only part that can cut somebody off
mid-sentence when it is wrong.
"""

from __future__ import annotations

import numpy as np
import pytest

from marvi_agent import kyutai_stt


class _Model:
    """A model on rails: each frame yields a scripted (text, pause) pair."""

    delay_seconds = 0.0

    def __init__(self, script: list[tuple[str, float]]) -> None:
        self.script = list(script)
        self.resets = 0
        self.steps = 0

    def reset(self) -> None:
        self.resets += 1

    def step(self, samples: np.ndarray, first: bool) -> tuple[str, float]:
        self.steps += 1
        return self.script.pop(0) if self.script else ("", 0.0)


def stream(monkeypatch, script, **settings) -> tuple[kyutai_stt.KyutaiStream, _Model]:
    for name, value in settings.items():
        monkeypatch.setenv(name, str(value))
    # No prefix in the tests: it is a second of silence per utterance, which
    # would mean thirteen scripted frames before the first interesting one.
    monkeypatch.setattr(kyutai_stt, "PREFIX_SECONDS", 0.0)
    recogniser = kyutai_stt.KyutaiSTT.__new__(kyutai_stt.KyutaiSTT)
    made = kyutai_stt.KyutaiStream.__new__(kyutai_stt.KyutaiStream)
    made._kyutai = recogniser
    made._said = ""
    made._transcribing = True
    made._pending = np.zeros(0, dtype=np.float32)
    made._open = False
    made._first = True
    made._ended_by_vad = 0
    made._high_for = 0
    return made, _Model(script)


def drive(made, model, script_length: int, threshold=0.5, hold=3) -> bool:
    """Feed frames until the VAD ends the turn, or the script runs out."""
    made._begin(model)
    for _ in range(script_length):
        _piece, done = model.step(np.zeros(kyutai_stt.FRAME_SAMPLES, np.float32), False)
        if _piece:
            made._said = (made._said + _piece).strip()
        made._high_for = made._high_for + 1 if done > threshold else 0
        if made._said and made._high_for >= hold:
            return True
    return False


def test_the_default_head_is_the_one_kyutai_ship() -> None:
    # Index 2 is the 2.0-second pause head, which is what Unmute uses and what
    # measured fewest premature endings here: one across fourteen clips.
    assert kyutai_stt.VAD_INDEX == 2
    assert kyutai_stt.VAD_THRESHOLD == 0.5
    assert kyutai_stt.VAD_HOLD == 3


def test_silence_before_speech_never_ends_a_turn(monkeypatch) -> None:
    """The heads are pause detectors and silence is a pause.

    Without this guard the first probe of the real signal crossed the threshold
    a second before the first word on every single clip.
    """
    made, model = stream(monkeypatch, [("", 0.99)] * 20)
    assert drive(made, model, 20) is False
    assert made._said == ""


def test_a_sustained_pause_after_speech_ends_the_turn(monkeypatch) -> None:
    made, model = stream(
        monkeypatch, [("hello", 0.0), ("", 0.9), ("", 0.9), ("", 0.9)]
    )
    assert drive(made, model, 4) is True


def test_a_one_frame_spike_does_not(monkeypatch) -> None:
    """The failure their issue tracker records: spikes on digits and silence.

    A bare threshold would end the turn in the middle of a phone number.
    """
    made, model = stream(
        monkeypatch,
        [("call", 0.0), ("", 0.99), ("five", 0.0), ("", 0.99), ("five", 0.0)],
    )
    assert drive(made, model, 5) is False
    assert made._said == "callfivefive"


def test_the_run_has_to_be_unbroken(monkeypatch) -> None:
    # Two high frames, one low, two high: five crossings' worth of probability
    # but never three in a row, so never a turn ending.
    made, model = stream(
        monkeypatch,
        [("hi", 0.0), ("", 0.9), ("", 0.9), ("", 0.1), ("", 0.9), ("", 0.9)],
    )
    assert drive(made, model, 6) is False


def test_the_hold_is_configurable(monkeypatch) -> None:
    made, model = stream(monkeypatch, [("hi", 0.0), ("", 0.9)])
    assert drive(made, model, 2, hold=1) is True


def test_a_bad_setting_falls_back_rather_than_crashing(monkeypatch) -> None:
    monkeypatch.setenv(kyutai_stt.VAD_THRESHOLD_SETTING, "very high")
    assert kyutai_stt._setting(kyutai_stt.VAD_THRESHOLD_SETTING, 0.5) == 0.5


def test_installed_wants_every_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(kyutai_stt, "MODEL_ROOT", tmp_path)
    assert kyutai_stt.installed() is False
    for name in (kyutai_stt.CONFIG, kyutai_stt.TOKENIZER, kyutai_stt.MIMI):
        (tmp_path / name).write_bytes(b"")
    # A partial download must read as missing, not load and fail inside moshi.
    assert kyutai_stt.installed() is False
    (tmp_path / kyutai_stt.WEIGHTS).write_bytes(b"")
    assert kyutai_stt.installed() is True


def test_the_checkpoint_is_the_one_with_the_heads() -> None:
    """The whole reason this recogniser exists is in one repository and not the other.

    `kyutai/stt-1b-en_fr` and `kyutai/stt-1b-en_fr-candle` are the same model
    under two names, and only the second carries `extra_heads`. The first
    benchmark used the first, and so measured this model with its one
    distinguishing feature absent.
    """
    import json
    from pathlib import Path

    catalog = json.loads(
        (Path(__file__).resolve().parents[3] / "config/stt-engines.json").read_text("utf-8")
    )
    kyutai = next(item for item in catalog["engines"] if item["id"] == "kyutai-1b")
    assert kyutai["model_id"] == "kyutai/stt-1b-en_fr-candle"
    assert kyutai["semantic_vad"] is True


@pytest.mark.parametrize("engine", ["parakeet-tdt", "nemotron-3.5", "kyutai-1b"])
def test_every_offered_engine_can_be_chosen(engine: str, monkeypatch) -> None:
    from marvi_agent.parakeet_stt import ENGINE_SETTING, chosen_engine

    monkeypatch.setenv(ENGINE_SETTING, engine)
    assert chosen_engine() == engine
