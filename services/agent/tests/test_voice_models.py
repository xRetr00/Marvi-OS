from pathlib import Path

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

