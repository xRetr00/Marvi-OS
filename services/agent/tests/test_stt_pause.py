"""How the recogniser is configured, and what it costs to get it wrong.

The pause-while-speaking machinery these tests used to cover is gone with the
engine that needed it: that existed because the recogniser and the speech
synthesis wanted the same GPU, and the recogniser runs on the processor now.
"""

from __future__ import annotations

import pytest

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


# -- what the recogniser must still do -------------------------------------
#
# These moved here with the behaviour. The engine changed twice; the ways it can
# silently stop working did not.


def test_silence_ends_the_utterance() -> None:
    """Nothing else declares a transcript final.

    LiveKit flushes the VAD and waits for the recogniser to say the utterance
    is over. One that only says so on an explicit flush says so never, and
    speech recognised perfectly stays interim forever:

        stt (partial): Hello Marvi, how you doing?  Are you here?

    and the model is never called, because as far as the session is concerned
    the sentence has not ended.
    """
    import inspect

    from marvi_agent import parakeet_stt

    source = inspect.getsource(parakeet_stt)

    assert "_SILENCE" in source
    assert "FINAL_TRANSCRIPT" in source
    # Still handled, because `end_input` does send one and it must not be lost.
    assert "_FlushSentinel" in source


def test_the_decoder_is_reset_between_utterances() -> None:
    """Otherwise the next sentence continues the last one.

    The recogniser keeps state across chunks -- that is what makes it
    incremental -- so ending an utterance without clearing it leaves the next
    carrying on. It shows up as a transcript repeating itself:

        Are you here?  Are you here?
    """
    import inspect

    from marvi_agent import parakeet_stt

    source = inspect.getsource(parakeet_stt.ParakeetStream._settle)
    final_at = source.index("FINAL_TRANSCRIPT")

    assert "reset()" in source[final_at:], "the decoder must be cleared after a final"


# -- how the transcript is assembled ------------------------------------------


class SplitWordASR:
    """A recogniser that hands a word back in two pieces.

    Which is the normal case, not a contrived one: a chunk boundary falls
    wherever two seconds of audio happen to end, and words do not wait for it.
    """

    #: 0.1s at 16kHz, so a couple of frames is a whole chunk.
    _initial_samples_needed = 1600
    chunk_samples = 1600

    def __init__(self) -> None:
        self._pieces: list[str] = []
        self._script = [" actu", "ally", " good"]

    def process_chunk(self, audio, is_last: bool) -> str:
        if self._script:
            self._pieces.append(self._script.pop(0))
        return self._pieces[-1].lstrip() if self._pieces else ""

    def get_full_text(self) -> str:
        return "".join(self._pieces).lstrip()

    def reset(self) -> None:
        self._pieces = []


@pytest.mark.asyncio
async def test_a_word_split_across_chunks_is_not_split_in_the_transcript() -> None:
    """"actu ally", "say ing", "Troubles hooting", "se arch".

    Every one of those is in the session log, and none of them is a mishearing:
    the recogniser returns the tokens decoded in each chunk with their leading
    space stripped, so joining the pieces with a space inserts a boundary the
    model never put there. The words were heard correctly and written wrong.
    """
    from livekit import rtc
    from livekit.agents import stt as lk_stt

    from marvi_agent.parakeet_stt import SAMPLE_RATE, ParakeetSTT

    recogniser = ParakeetSTT()
    recogniser._asr = SplitWordASR()
    stream = recogniser.stream()

    silence = b"\x00\x00" * 1600
    for _ in range(3):
        stream.push_frame(
            rtc.AudioFrame(
                data=silence, sample_rate=SAMPLE_RATE, num_channels=1, samples_per_channel=1600
            )
        )
    stream.end_input()

    finals = [
        event.alternatives[0].text
        async for event in stream
        if event.type == lk_stt.SpeechEventType.FINAL_TRANSCRIPT
    ]
    await stream.aclose()

    assert finals, "the recogniser produced no final transcript"
    assert "actu ally" not in finals[-1], f"word split at a chunk boundary: {finals[-1]!r}"
    assert finals[-1] == "actually good"


def test_the_recogniser_settings_come_from_the_gateway() -> None:
    """Choosing the graphics card in Settings did nothing.

    This process's environment is fixed when the desktop spawns it, so a
    setting written by the UI is written somewhere the Agent never reads — the
    same hole the voice had, and the wake word before that. The log went on
    saying `parakeet ready on cpu` after the setting had been changed, which
    reads as a switch that is not wired to anything.
    """
    import inspect

    from marvi_agent import session

    assert hasattr(session, "apply_speech_settings")
    # Applied before the models are built, or it applies to nothing.
    prewarm = inspect.getsource(session.prewarm)
    assert "apply_speech_settings()" in prewarm
    # `build_stt()` now, because which recogniser to build is itself one of
    # the settings the Gateway answers with.
    assert prewarm.index("apply_speech_settings()") < prewarm.index("build_stt()")


def test_a_gateway_that_cannot_answer_leaves_the_defaults() -> None:
    """Never raises: no answer means the behaviour there was before."""
    import os

    from marvi_agent.session import apply_speech_settings

    before = os.environ.get("MARVI_STT_DEVICE")
    os.environ["MARVI_GATEWAY_URL"] = "http://127.0.0.1:9"  # nothing listens there
    try:
        apply_speech_settings()
    finally:
        os.environ.pop("MARVI_GATEWAY_URL", None)

    assert os.environ.get("MARVI_STT_DEVICE") == before


def test_the_left_context_is_the_one_that_was_measured() -> None:
    """The final flush is the dead air between somebody finishing a sentence
    and Marvi knowing what they said, and it is what this window pays for.

    Measured with a full buffer: 1591ms at ten seconds, 918ms at four. Measured
    for accuracy on synthesised English scored against the text it was made
    from: 2.3% word errors at every setting, identical. So the window bought
    nothing and cost two thirds of a second per turn.

    Pinned because it is a number with evidence behind it, and the next person
    to change it should have to replace the evidence.
    """
    from marvi_agent.parakeet_stt import DEFAULT_LEFT_CONTEXT

    assert DEFAULT_LEFT_CONTEXT == 4.0


# -- which recogniser --------------------------------------------------------


def test_the_multilingual_model_is_the_default(monkeypatch) -> None:
    from marvi_agent.parakeet_stt import PARAKEET_ROOT, chosen_model

    monkeypatch.delenv("MARVI_STT_LANGUAGE", raising=False)

    assert chosen_model() == PARAKEET_ROOT


def test_english_selects_the_english_only_model(monkeypatch, tmp_path) -> None:
    """The only real language lock there is. v3 takes no language argument, so
    "understand English only" is a model choice or it is nothing."""
    import marvi_agent.parakeet_stt as module

    english = tmp_path / "parakeet-tdt-0.6b-v2-onnx"
    english.mkdir()
    (english / "encoder-model.onnx").write_bytes(b"x")
    monkeypatch.setattr(module, "PARAKEET_ENGLISH_ROOT", english)
    monkeypatch.setenv("MARVI_STT_LANGUAGE", "en")

    assert module.chosen_model() == english


def test_english_without_the_model_falls_back_and_says_so(monkeypatch, tmp_path, caplog) -> None:
    """Hearing you in a model that guesses beats not hearing you -- but silence
    about it is how a setting looks like it did something."""
    import logging

    import marvi_agent.parakeet_stt as module

    monkeypatch.setattr(module, "PARAKEET_ENGLISH_ROOT", tmp_path / "absent")
    monkeypatch.setenv("MARVI_STT_LANGUAGE", "en")

    with caplog.at_level(logging.WARNING, logger="marvi.voice"):
        assert module.chosen_model() == module.PARAKEET_ROOT

    assert "not installed" in caplog.text


def test_the_reported_model_is_the_one_loaded(tmp_path) -> None:
    """The Voice page reads this. Naming v3 while v2 runs is why nobody could
    tell which language rule was in force."""
    from marvi_agent.parakeet_stt import ParakeetSTT

    assert ParakeetSTT(model_dir=tmp_path / "parakeet-tdt-0.6b-v2-onnx").model == (
        "parakeet-tdt-0.6b-v2"
    )


def test_the_recogniser_is_given_a_timeout_to_produce_words() -> None:
    """`observability` has listened for `user_transcription_timeout` the whole
    time, for an event that could not fire because the option that produces it
    was never passed. A warning nobody can trigger is decoration.

    It is the failure LiveKit's own writing on short utterances names first:
    the recogniser silently produces no final transcript for a brief answer,
    turn-taking never completes, and the agent goes quiet. Marvi's log has the
    shape of it -- thirty-four turns that went listening, thinking, and back to
    listening without her speaking."""
    import inspect

    from marvi_agent import session as session_module

    built = inspect.getsource(session_module.build_session)

    assert "transcription_timeout=TRANSCRIPTION_TIMEOUT" in built
    assert 0 < session_module.TRANSCRIPTION_TIMEOUT <= 4


def test_she_says_something_when_the_words_never_arrive() -> None:
    """Silence is the worst of the three outcomes. A wrong transcript can be
    corrected and a refusal argued with, but silence is indistinguishable from
    not listening, so the person repeats themselves into nothing."""
    import inspect

    from marvi_agent import observability, session

    handler = inspect.getsource(observability.attach)

    assert "session.say(MISHEARD)" in handler
    assert session.MISHEARD
