import pytest

from marvi_agent.runtime import (
    OPENCODE_GO_BASE_URL,
    AgentConfig,
    VoiceStackPendingError,
    require_selected_voice_adapters,
)


def test_config_requires_opencode_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENCODE_GO_API_KEY"):
        AgentConfig.from_env()


def test_config_defaults_to_fast_voice_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
    monkeypatch.delenv("MARVI_LLM_MODEL", raising=False)
    monkeypatch.delenv("MARVI_LLM_BASE_URL", raising=False)

    config = AgentConfig.from_env()

    assert config.model == "deepseek-v4-flash"
    assert config.base_url == OPENCODE_GO_BASE_URL


def test_worker_refuses_to_fake_an_unselected_voice_stack() -> None:
    with pytest.raises(VoiceStackPendingError, match="streaming STT/TTS"):
        require_selected_voice_adapters(stt=None, tts=None)

    require_selected_voice_adapters(stt=object(), tts=object())
