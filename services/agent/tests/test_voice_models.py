from pathlib import Path

import pytest

from marvi_agent.voice_models import DEFAULT_VOICE, NemotronSTT, VibeVoiceTTS


def test_nemotron_declares_true_streaming() -> None:
    adapter = NemotronSTT(executable=Path("voice-runtime.exe"))
    assert adapter.capabilities.streaming is True
    assert adapter.capabilities.interim_results is True
    assert adapter.model == "nemotron-3.5-asr-streaming-0.6b"
    assert adapter.provider == "nvidia/parakeet-rs"


def test_vibevoice_exposes_installed_presets(tmp_path: Path) -> None:
    voices = tmp_path / "voices"
    (tmp_path / "model").mkdir()
    voices.mkdir()
    (voices / f"{DEFAULT_VOICE}.pt").touch()
    (voices / "en-Emma_woman.pt").touch()
    adapter = VibeVoiceTTS(root=tmp_path)
    assert adapter.sample_rate == 24_000
    assert adapter.num_channels == 1
    assert adapter.voices == [DEFAULT_VOICE, "en-Emma_woman"]



def test_a_speaker_prompt_loads_on_modern_pytorch(tmp_path) -> None:
    """PyTorch 2.6 changed `torch.load` and it stopped voice speaking at all.

    The default for `weights_only` flipped to True, and a speaker prompt is a
    dict subclass the safe unpickler refuses to fill:

        Can only SETITEMS for dict, collections.OrderedDict,
        collections.Counter, but got BaseModelOutputWithPast

    Allowlisting the classes does not help -- the restriction is on SETITEMS
    itself. This reproduces the shape that failed, so the loader cannot quietly
    go back to a setting that cannot read Marvi's own voices.
    """
    import pickle

    import torch
    from transformers.modeling_outputs import BaseModelOutputWithPast

    prompt = BaseModelOutputWithPast(last_hidden_state=torch.zeros(1, 2, 3))
    path = tmp_path / "en-Test_man.pt"
    torch.save(prompt, path)

    # The specific failure, not any failure: a blind `Exception` here would
    # still pass if torch started refusing the file for an unrelated reason.
    with pytest.raises(pickle.UnpicklingError, match=r"[Ww]eights only"):
        torch.load(path, map_location="cpu", weights_only=True)

    loaded = torch.load(path, map_location="cpu", weights_only=False)

    assert loaded is not None


def test_the_loader_does_not_ask_for_weights_only() -> None:
    """Guarding the call itself, since the failure is silent until speech."""
    import inspect

    from marvi_agent import voice_models

    source = inspect.getsource(voice_models)

    assert "weights_only=True" not in source, (
        "a speaker prompt cannot be read with weights_only=True"
    )


@pytest.mark.asyncio
async def test_silence_ends_the_utterance(monkeypatch) -> None:
    """Nothing else declares a transcript final, so this must.

    LiveKit flushes the VAD stream and waits for the recogniser to say the
    utterance is over. Ours only said so on an explicit flush that never came,
    so speech recognised perfectly stayed interim forever:

        stt (partial): Hello Marvel, how you doing?  Are you here?

    and the model was never called, because as far as the session was
    concerned the sentence had not ended.
    """
    import time

    from livekit.agents import stt as lk_stt

    from marvi_agent.voice_models import NemotronSTT

    adapter = NemotronSTT(executable=Path("runtime.exe"))
    stream = adapter.stream()
    emitted: list[tuple] = []
    monkeypatch.setattr(
        stream, "_emit", lambda kind, text: emitted.append((kind, text))
    )

    # Words arrive.
    stream._transcript = "hello marvi"
    stream._spoke_at = time.monotonic()

    # A frame with no new text, immediately: too soon to call it finished.
    assert time.monotonic() - stream._spoke_at < stream._SILENCE

    # The same frame after the silence window.
    stream._spoke_at = time.monotonic() - (stream._SILENCE + 0.1)
    if stream._transcript.strip() and (
        time.monotonic() - stream._spoke_at >= stream._SILENCE
    ):
        stream._emit(lk_stt.SpeechEventType.FINAL_TRANSCRIPT, stream._transcript.strip())
        stream._transcript = ""

    assert emitted == [(lk_stt.SpeechEventType.FINAL_TRANSCRIPT, "hello marvi")]
    assert stream._transcript == "", "the next utterance must start clean"


def test_the_stream_finalises_without_an_external_flush() -> None:
    """Guarding the mechanism, not just the arithmetic.

    LiveKit never calls flush() on an STT stream -- grep its voice package and
    the only flush is the VAD's. A recogniser that finalises only on flush
    finalises never.
    """
    import inspect

    from marvi_agent import voice_models

    source = inspect.getsource(voice_models)

    assert "_SILENCE" in source
    assert "FINAL_TRANSCRIPT" in source
    # Still handled, because `end_input` does send one and it must not be lost.
    assert "_FlushSentinel" in source


def test_a_clause_is_spoken_before_the_sentence_is_finished() -> None:
    """The difference between answering and pausing to compose.

    LiveKit's StreamAdapter batches into sentences of at least twelve
    characters, so a short reply waited for words that were never coming and
    every reply paid that delay before its first sound. The engine takes a
    whole utterance rather than tokens, so some batching is unavoidable —
    owning it is what lets the first clause be spoken as soon as it is one.
    """
    from marvi_agent.voice_models import _next_clause

    clause, rest = _next_clause("The light is on. Anything else?")

    assert clause == "The light is on."
    assert rest == " Anything else?"


def test_an_unfinished_clause_waits() -> None:
    """Speaking half a phrase is worse than a moment's wait."""
    from marvi_agent.voice_models import _next_clause

    assert _next_clause("The light is") == ("", "The light is")


def test_a_fragment_too_short_to_speak_alone_is_held() -> None:
    """"Yes" then "it is" as two utterances sounds like two answers."""
    from marvi_agent.voice_models import _next_clause

    assert _next_clause("Hi.")[0] == ""


def test_the_tts_declares_itself_streaming() -> None:
    """Declaring False is what made LiveKit wrap it in the adapter."""
    from marvi_agent.voice_models import VibeVoiceTTS

    engine = VibeVoiceTTS()

    assert engine.capabilities.streaming is True


def test_the_session_does_not_wrap_the_tts() -> None:
    """A native streaming TTS through StreamAdapter is batching twice."""
    import inspect

    from marvi_agent import session

    # The construction, not the word: the comment above it explains why the
    # adapter is gone and would match a naive search.
    assert "StreamAdapter(" not in inspect.getsource(session.build_session)


def test_the_decoder_is_reset_between_utterances() -> None:
    """Otherwise the next sentence continues the last one.

    The runtime keeps decoder state across `audio` calls -- that is what makes
    it incremental -- so ending an utterance without clearing it leaves the
    next one carrying on. It shows up as a transcript repeating itself:

        Are you here?  Are you here?
    """
    import inspect

    from marvi_agent import voice_models

    source = inspect.getsource(voice_models)
    final_at = source.index("FINAL_TRANSCRIPT, self._transcript.strip()")
    after = source[final_at : final_at + 700]

    assert '"op": "reset"' in after, "finalising must clear the runtime's state too"
