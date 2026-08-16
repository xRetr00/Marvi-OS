import httpx
import pytest

from marvi_agent.runtime import (
    AgentConfig,
    ProviderUnavailableError,
    VoiceStackPendingError,
    require_selected_voice_adapters,
)


def gateway(status: int, body: dict | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/providers/voice"
        return httpx.Response(status, json=body or {})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_the_worker_takes_its_provider_from_the_gateway() -> None:
    config = AgentConfig.from_gateway(
        gateway(
            200,
            {
                "provider": "ollama",
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "llama4:latest",
                "api_key": "local",
            },
        )
    )

    # Nothing about which provider this is lives in the worker.
    assert config.provider == "ollama"
    assert config.base_url == "http://127.0.0.1:11434/v1"
    assert config.model == "llama4:latest"


def test_no_provider_is_a_clear_message_not_a_crash() -> None:
    with pytest.raises(ProviderUnavailableError, match="control center"):
        AgentConfig.from_gateway(gateway(503))


def test_an_unreachable_gateway_says_so() -> None:
    def dead(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderUnavailableError, match="unreachable"):
        AgentConfig.from_gateway(httpx.Client(transport=httpx.MockTransport(dead)))


def test_an_incomplete_answer_is_refused() -> None:
    with pytest.raises(ProviderUnavailableError, match="incomplete"):
        AgentConfig.from_gateway(gateway(200, {"provider": "x"}))


def test_worker_refuses_to_fake_an_unselected_voice_stack() -> None:
    with pytest.raises(VoiceStackPendingError, match="streaming STT/TTS"):
        require_selected_voice_adapters(stt=None, tts=None)

    require_selected_voice_adapters(stt=object(), tts=object())
