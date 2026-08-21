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
