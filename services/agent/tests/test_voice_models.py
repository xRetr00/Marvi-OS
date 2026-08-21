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
