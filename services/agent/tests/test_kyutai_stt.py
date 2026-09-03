"""The Kyutai recogniser, and the guards around its end-of-turn signal.

`moshi` and a 2.3 GB checkpoint are not importable in a unit test, so the model
is a stand-in. What is worth pinning here is not the transcription -- the
benchmark measures that -- but the turn-taking logic, which is the only reason
this recogniser is carried at all and the only part that can cut somebody off
mid-sentence when it is wrong.
"""

from __future__ import annotations

import asyncio
import threading

import numpy as np
import pytest

from marvi_agent import kyutai_stt


class _Model:
    """A model on rails: each frame yields a scripted (text, pause) pair."""

    delay_seconds = 0.0

    def __init__(self, script: list[tuple[str, float]], tail: str = "") -> None:
        self.script = list(script)
        self.resets = 0
        self.steps = 0
        #: What the closing silence shakes out of the model, and how it was got.
        self.tail = tail
        self.flushes: list[int] = []

    def reset(self) -> None:
        self.resets += 1

    def step(self, samples: np.ndarray, first: bool) -> tuple[str, float]:
        self.steps += 1
        return self.script.pop(0) if self.script else ("", 0.0)

    def flush(self, frames: int) -> tuple[str, float]:
        self.flushes.append(int(frames))
        return self.tail, 0.0


class _Channel:
    """Somewhere for the stream to put events, remembering which thread sent.

    The thread matters: `Chan.send_nowait` wakes the waiting coroutine with
    `future.set_result`, which is only valid on the loop's own thread. See
    `test_events_are_sent_from_the_event_loop`.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[object, str]] = []
        self.threads: set[int] = set()

    def send_nowait(self, event) -> None:
        self.sent.append((event.type, event.alternatives[0].text))
        self.threads.add(threading.get_ident())


def stream(monkeypatch, script, **settings) -> tuple[kyutai_stt.KyutaiStream, _Model]:
    tail = settings.pop("tail", "")
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
    made._peak = 0.0
    made._spoke_at = 0.0
    made._event_ch = _Channel()
    return made, _Model(script, tail=tail)


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


def test_the_turn_is_committed_however_it_ended(monkeypatch) -> None:
    """The end of the turn has to reach LiveKit even when the timer called it.

    This is the bug that made Marvi go silent in a live call. `END_OF_SPEECH`
    was emitted only when the pause heads ended the turn, on the reasoning that
    a turn ended by the fallback timer should not claim to be more than an
    ordinary silence ending. But the session runs `turn_detection="stt"` for
    this recogniser, and in that mode `audio_recognition` commits a turn on
    nothing else: `_vad_base_turn_detection` is false, and the VAD's own
    end-of-speech is gated behind `_user_turn_committed`, which only the STT
    end-of-speech branch ever sets.

    So a turn the heads did not call was transcribed and then dropped on the
    floor -- "Hey, Marvi, how are you doing?" reached the log at 13:51:44 and
    was never answered. Both endings, because only one of them regressed and a
    test for one of them would not have caught it.
    """
    from livekit.agents import stt as livekit_stt

    for why in ("the model", "the timer"):
        made, model = stream(monkeypatch, [], tail="")
        made._open = True
        made._said = "hey marvi"
        asyncio.run(made._settle(model, why))
        kinds = [kind for kind, _text in made._event_ch.sent]
        assert livekit_stt.SpeechEventType.FINAL_TRANSCRIPT in kinds
        assert livekit_stt.SpeechEventType.END_OF_SPEECH in kinds, (
            f"a turn ended by {why} never reaches the LLM"
        )


def test_a_turn_with_nothing_in_it_ends_nothing(monkeypatch) -> None:
    # The other direction: silence that never became words is not a turn, and
    # committing it would have Marvi answer an empty string.
    made, model = stream(monkeypatch, [])
    made._open = True
    made._said = ""
    asyncio.run(made._settle(model, "the timer"))
    assert made._event_ch.sent == []


def test_the_closing_silence_is_one_round_trip(monkeypatch) -> None:
    """Kyutai's flush, asked for once instead of seven times.

    The trick is theirs -- the text stream lags the audio by
    `audio_delay_seconds`, so their own script appends that many frames of
    silence and reads the tail off the end. The cost was ours: a frame at a
    time meant seven JSON writes and seven blocking pipe reads in the gap
    between the speaker stopping and Marvi answering, measured live at 1.53 s.
    """
    made, model = stream(monkeypatch, [], tail=" doing?")
    model.delay_seconds = 0.5
    made._open = True
    made._said = "how are you"
    asyncio.run(made._settle(model, "the timer"))
    assert model.flushes == [7], "the flush is back to a round trip per frame"
    assert model.steps == 0
    # And the tail it shook loose is part of the transcript, not lost.
    assert (" ".join(text for _kind, text in made._event_ch.sent)).strip().startswith(
        "how are you doing?"
    )


def test_the_opening_silence_is_one_round_trip(monkeypatch) -> None:
    # The prefix runs on the first frame of every utterance -- the moment the
    # person starts talking -- so twelve round trips there sat on the critical
    # path of every single turn.
    made, model = stream(monkeypatch, [])
    monkeypatch.setattr(kyutai_stt, "PREFIX_SECONDS", 1.0)
    made._begin(model)
    assert model.flushes == [12]
    assert model.steps == 0


def test_events_are_sent_from_the_event_loop(monkeypatch) -> None:
    """Where an event is sent from is not a detail; it is 1.53 s of silence.

    `Chan.send_nowait` appends to a deque and then wakes the waiting coroutine
    with `future.set_result` -- valid only on the loop's own thread. Sent from
    a worker, the future resolves but the loop is never signalled: it sleeps in
    its selector until something else wakes it, and only then sees the
    transcript. Nothing is dropped, which is why this read as a slow model
    rather than a missed wakeup.

    `_settle` used to run wholesale through `asyncio.to_thread` and emit from
    in there. Live, that put 1.53 s between "turn ended by the timer" in the
    log and the transcript reaching the session -- on top of every reply.
    """
    made, model = stream(monkeypatch, [], tail=" doing?")
    made._open = True
    made._said = "how are you"

    async def run() -> int:
        await made._settle(model, "the timer")
        return threading.get_ident()

    loop_thread = asyncio.run(run())
    assert made._event_ch.sent, "nothing was emitted at all"
    assert made._event_ch.threads == {loop_thread}, (
        "an event was sent from a worker thread; the loop will not be woken"
    )


def test_audio_that_became_no_words_still_resets_the_model(monkeypatch) -> None:
    """`_settle` is the only thing that resets the recogniser.

    The fallback timer is gated on `self._said`, which is right for ending a
    turn -- silence that never became words is not a turn -- and wrong for the
    model underneath, which is left open holding whatever state it had. Live,
    the failures came in pairs: audio transcribed to nothing, Marvi apologised,
    the person repeated themselves, and that transcribed to nothing either.
    """
    made, model = stream(monkeypatch, [])
    made._open = True
    made._said = ""
    made._opened_at = 0.0  # long ago

    # Nothing to emit -- an empty transcript is not a turn and must not become
    # one -- but the stream has to be closed so the next `_begin` resets.
    asyncio.run(made._settle(model, "nothing heard"))
    assert made._event_ch.sent == []
    assert made._open is False

    made._begin(model)
    assert model.resets == 1, "the next utterance did not start from a clean model"
