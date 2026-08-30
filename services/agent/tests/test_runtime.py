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


def test_end_of_turn_is_decided_locally() -> None:
    """A cloud call in the turn loop of a local-first assistant.

    `inference.TurnDetector` takes base_url, api_key and api_secret and asks
    LiveKit Inference. Marvi runs against a self-hosted LiveKit with local
    keys, so it could never reach it — and it failed silently in the worst
    possible way: end of turn never resolved, the STT stream was never
    flushed, no FINAL_TRANSCRIPT was emitted, and speech recognised perfectly
    stayed interim forever while the model was never called.
    """
    from marvi_agent.runtime import build_local_turn_detector

    mode = build_local_turn_detector()

    assert mode == "vad", "end of turn must not depend on a service this install cannot reach"
    assert isinstance(mode, str), "a detector object here means a network round trip per turn"


def test_a_spoken_reply_is_bounded() -> None:
    """Unset means the model's whole context, and the provider charges for it.

    The plugin sent no limit, so OpenRouter saw a request for 65,536 tokens,
    reserved credit against all of them, and refused every voice turn:

        402: This request requires more credits, or fewer max_tokens. You
        requested up to 65536 tokens, but can only afford 14191.

    It is also wrong on its own terms. Three hundred tokens is about a minute
    of speech, and a spoken answer longer than that is one nobody asked for.
    """
    from marvi_agent.runtime import VOICE_REPLY_TOKENS, AgentConfig, build_llm

    model = build_llm(AgentConfig(api_key="k", model="m", base_url="https://x/v1"))

    assert 0 < VOICE_REPLY_TOKENS <= 1000
    assert model._opts.max_completion_tokens == VOICE_REPLY_TOKENS


# -- what the voice request actually carries ---------------------------------


def test_the_configured_route_is_used_rather_than_one_invented_here() -> None:
    """The Agent used to hardcode `sort: latency`.

    That duplicated a policy the Gateway already computes from a setting the
    user can change, and pinned a constraint the numbers do not support: best
    first-token times are the same with it and without, and what varies by
    twenty times run to run is which upstream OpenRouter picks.
    """
    from marvi_agent.runtime import AgentConfig, voice_body

    body = voice_body(
        AgentConfig(
            api_key="k",
            model="m",
            base_url="https://openrouter.ai/api/v1",
            route={"sort": "throughput"},
        )
    )

    assert body["provider"] == {"sort": "throughput"}


def test_no_configured_route_means_no_routing_field() -> None:
    """Letting OpenRouter choose is a valid answer and the default one."""
    from marvi_agent.runtime import AgentConfig, voice_body

    body = voice_body(
        AgentConfig(api_key="k", model="m", base_url="https://openrouter.ai/api/v1")
    )

    assert "provider" not in body


def test_voice_asks_for_reasoning_to_be_off() -> None:
    """Thinking happens before the first token, and the first token is the
    whole experience of a spoken turn."""
    from marvi_agent.runtime import AgentConfig, voice_body

    body = voice_body(
        AgentConfig(api_key="k", model="m", base_url="https://openrouter.ai/api/v1")
    )

    assert body["reasoning"] == {"enabled": False, "exclude": True}


def test_every_provider_is_told_to_stop_thinking_in_its_own_dialect() -> None:
    """Reasoning off is not an optimisation on a spoken turn. Measured on the
    model that ships: 4.25s and 356 reasoning tokens by default, 1.48s and none
    with it off.

    It used to be asked of OpenRouter alone and nobody else, so changing
    provider turned thinking back on and the voice path became slow again with
    nothing in the logs to say why. There is no shared field, so each is
    spelled the way that provider spells it."""
    from marvi_agent.runtime import AgentConfig, voice_body

    def body(url: str) -> dict:
        return voice_body(AgentConfig(api_key="k", model="m", base_url=url))

    # Ollama and vLLM turn Qwen3's `<think>` block off at the template.
    assert body("http://127.0.0.1:1234/v1") == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    # Anything else gets OpenAI's spelling, which the endpoints with a knob
    # have settled on and the ones without ignore.
    assert body("https://api.deepseek.com") == {"reasoning_effort": "none"}


def test_no_provider_is_left_thinking() -> None:
    """The property, rather than three examples of it. A provider added later
    must not be the one that quietly gets reasoning back."""
    from marvi_agent.runtime import AgentConfig, voice_body

    for url in (
        "https://openrouter.ai/api/v1",
        "http://127.0.0.1:1234/v1",
        "http://localhost:11434/v1",
        "https://api.deepseek.com",
        "https://opencode.ai/zen/go/v1",
        "https://api.groq.com/openai/v1",
    ):
        asked = voice_body(AgentConfig(api_key="k", model="m", base_url=url))
        assert asked, f"{url} was told nothing about reasoning"


def test_a_spoken_reply_is_capped_by_speech_not_by_the_context_window() -> None:
    """It was a twentieth of the context, capped at 1024 -- so on a 128k model,
    1024 tokens: roughly 770 words, or five minutes of continuous speech. A
    real conversation produced a single reply of 48 seconds of audio.

    How long somebody wants to be spoken at has nothing to do with how much the
    model can hold. The mistake was the shape, not the number.
    """
    from marvi_agent.runtime import VOICE_REPLY_TOKENS, reply_tokens

    assert reply_tokens(128_000) == VOICE_REPLY_TOKENS
    assert reply_tokens(1_000_000) == VOICE_REPLY_TOKENS
    assert reply_tokens(0) == VOICE_REPLY_TOKENS
    # About a minute of speech. Long enough for a real explanation, short
    # enough that a model which has started drifting is cut off.
    assert 150 <= VOICE_REPLY_TOKENS <= 400


def test_a_tiny_context_lowers_the_cap_but_nothing_raises_it() -> None:
    """A model too small to hold the conversation and the reply should not be
    asked to reserve the whole window for the reply."""
    from marvi_agent.runtime import VOICE_REPLY_TOKENS, reply_tokens

    assert reply_tokens(800) < VOICE_REPLY_TOKENS
    assert reply_tokens(800) >= 64


def test_turn_taking_is_not_faster_than_a_person_pauses() -> None:
    """One sentence became two turns two seconds apart, because a quarter
    second of silence ended the turn and people pause longer than that in the
    middle of a thought. These are LiveKit's own defaults."""
    import inspect

    from marvi_agent import session

    source = inspect.getsource(session.build_session)

    assert '"min_delay": 0.5' in source
    # And the other half: a quarter second of the user's voice cut her off
    # mid-reply, and the resumed fragments were stitched into one turn.
    assert '"min_duration": 0.5' in source
