"""Provider profiles.

The interesting behaviour is request shaping: three wire formats, streaming,
reasoning effort, and prompt caching all have to come out right, because
getting them wrong is either an API error or a silent cost.
"""

from __future__ import annotations

import pytest

from marvi_gateway.providers import (
    CachePolicy,
    LimitPolicy,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderProfile,
    ReasoningPolicy,
    Usage,
    all_profiles,
    configured_profiles,
    get,
    select,
)

MESSAGES = [
    {"role": "system", "content": "You are Marvi."},
    {"role": "user", "content": "hello"},
]


def profile(**changes) -> ProviderProfile:
    base = ProviderProfile(
        name="test", default_base_url="https://x.test/v1", key_env=("TEST_KEY",)
    )
    return base.with_overrides(**changes)


# -- registry ---------------------------------------------------------------


def test_only_finished_providers_are_registered() -> None:
    names = {p.name for p in all_profiles()}
    assert names == {"ollama", "lmstudio", "llamacpp", "opencode-zen", "opencode-go"}


def test_zen_and_go_are_separate_providers() -> None:
    zen, go = get("opencode-zen"), get("opencode-go")

    assert zen.access_path == "api"
    assert go.access_path == "plan"
    assert zen.default_base_url != go.default_base_url
    assert zen.limits.style == "credit"
    assert go.limits.style == "rolling_windows"


def test_aliases_resolve() -> None:
    assert get("go").name == "opencode-go"
    assert get("zen").name == "opencode-zen"
    assert get("lm-studio").name == "lmstudio"
    assert get("vllm").name == "llamacpp"


def test_an_unknown_provider_is_refused() -> None:
    with pytest.raises(ProviderError, match="unknown provider"):
        get("nope")


# -- configuration comes from the environment -------------------------------


def test_nothing_is_hardcoded_at_the_call_site(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_OLLAMA_URL", "http://192.168.1.9:11434/v1")
    monkeypatch.setenv("MARVI_OLLAMA_MODEL", "llama4:latest")
    ollama = get("ollama")

    assert ollama.base_url() == "http://192.168.1.9:11434/v1"
    assert ollama.model_for() == "llama4:latest"


def test_local_providers_need_no_key(monkeypatch) -> None:
    monkeypatch.delenv("MARVI_OLLAMA_URL", raising=False)
    assert get("ollama").configured() is True


def test_a_key_provider_is_unconfigured_without_one(monkeypatch) -> None:
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    assert get("opencode-go").configured() is False
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "k")
    assert get("opencode-go").configured() is True


def test_a_local_provider_with_no_endpoint_is_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("MARVI_LOCAL_OPENAI_URL", raising=False)
    assert get("llamacpp").configured() is False


def test_selection_prefers_local(monkeypatch) -> None:
    monkeypatch.delenv("MARVI_PROVIDER", raising=False)
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "k")
    # Local costs nothing and works offline, so it wins by default.
    assert select().access_path == "local"


def test_an_explicit_choice_wins(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_PROVIDER", "opencode-go")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "k")
    assert select().name == "opencode-go"


def test_no_configured_provider_is_a_clear_error(monkeypatch) -> None:
    monkeypatch.delenv("MARVI_PROVIDER", raising=False)
    for name in ("OPENCODE_GO_API_KEY", "OPENCODE_ZEN_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "marvi_gateway.providers.base.configured_profiles", lambda: []
    )
    with pytest.raises(ProviderNotConfiguredError):
        select()


# -- api shapes -------------------------------------------------------------


def test_chat_completions_shape() -> None:
    body = profile().build_request(MESSAGES, model="m", max_tokens=100)

    assert body["model"] == "m"
    assert body["messages"] == MESSAGES  # system stays inline
    assert body["max_tokens"] == 100
    assert "stream" not in body


def test_streaming_asks_for_usage_too() -> None:
    body = profile().build_request(MESSAGES, stream=True)

    assert body["stream"] is True
    # Without this many OpenAI-compatible servers omit usage on streams and the
    # token budget goes blind.
    assert body["stream_options"] == {"include_usage": True}


def test_streaming_is_dropped_when_unsupported() -> None:
    body = profile(supports_streaming=False).build_request(MESSAGES, stream=True)
    assert "stream" not in body


def test_responses_api_shape() -> None:
    body = profile(api_mode="responses").build_request(MESSAGES, max_tokens=64)

    assert body["input"] == MESSAGES
    assert body["max_output_tokens"] == 64
    assert "messages" not in body


def test_anthropic_shape_lifts_the_system_prompt_out() -> None:
    body = profile(api_mode="anthropic").build_request(MESSAGES)

    # Anthropic takes system beside the messages, not inside them.
    assert body["system"][0]["text"] == "You are Marvi."
    assert all(m["role"] != "system" for m in body["messages"])
    assert body["max_tokens"] == 1024


def test_endpoints_differ_per_api_shape() -> None:
    assert profile().endpoint().endswith("/chat/completions")
    assert profile(api_mode="responses").endpoint().endswith("/responses")
    assert profile(api_mode="anthropic").endpoint().endswith("/v1/messages")


def test_anthropic_authenticates_with_a_header_not_a_bearer(monkeypatch) -> None:
    monkeypatch.setenv("TEST_KEY", "secret")
    headers = profile(api_mode="anthropic").headers()

    assert headers["x-api-key"] == "secret"
    assert "authorization" not in headers
    assert headers["anthropic-version"]


# -- reasoning effort -------------------------------------------------------


def test_effort_is_only_sent_to_providers_that_accept_it() -> None:
    plain = profile().build_request(MESSAGES, effort="high")
    assert "reasoning_effort" not in plain

    thinking = profile(
        reasoning=ReasoningPolicy(style="effort", levels=("low", "high"), default="low")
    )
    assert thinking.build_request(MESSAGES, effort="high")["reasoning_effort"] == "high"


def test_an_unsupported_effort_falls_back_to_the_default() -> None:
    thinking = profile(
        reasoning=ReasoningPolicy(style="effort", levels=("low", "high"), default="low")
    )
    assert thinking.build_request(MESSAGES, effort="ludicrous")["reasoning_effort"] == "low"


def test_anthropic_takes_a_thinking_budget_not_an_effort_level() -> None:
    body = profile(
        api_mode="anthropic", reasoning=ReasoningPolicy(style="budget_tokens")
    ).build_request(MESSAGES, effort="2048")

    assert body["thinking"] == {"type": "enabled", "budget_tokens": 2048}


# -- caching, the cost lever ------------------------------------------------


def test_caching_is_not_requested_from_providers_that_lack_it() -> None:
    body = profile().build_request(MESSAGES, cache_prefix=True)
    assert "prompt_cache_key" not in body


def test_a_cache_key_provider_gets_a_stable_key() -> None:
    body = profile(cache=CachePolicy(style="cache_key")).build_request(
        MESSAGES, cache_prefix=True
    )
    # Stable across turns on purpose: the system prompt does not change.
    assert body["prompt_cache_key"] == "marvi-system"


def test_anthropic_marks_a_breakpoint_on_the_system_block() -> None:
    body = profile(
        api_mode="anthropic", cache=CachePolicy(style="explicit_breakpoints")
    ).build_request(MESSAGES, cache_prefix=True)

    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_no_breakpoint_when_caching_was_not_asked_for() -> None:
    body = profile(
        api_mode="anthropic", cache=CachePolicy(style="explicit_breakpoints")
    ).build_request(MESSAGES)

    assert "cache_control" not in body["system"][0]


# -- usage accounting -------------------------------------------------------


def test_openai_usage_including_cached_and_reasoning_tokens() -> None:
    usage = profile().read_usage(
        {
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 50,
                "prompt_tokens_details": {"cached_tokens": 900},
                "completion_tokens_details": {"reasoning_tokens": 20},
            }
        }
    )

    assert usage.input == 1000
    assert usage.cached_input == 900
    assert usage.reasoning == 20
    # 100 fresh input + 50 output. This is the number the budget should see.
    assert usage.billable == 150


def test_anthropic_usage_counts_cache_reads_as_input() -> None:
    usage = profile(api_mode="anthropic").read_usage(
        {"usage": {"input_tokens": 100, "cache_read_input_tokens": 900, "output_tokens": 50}}
    )

    assert usage.input == 1000
    assert usage.cached_input == 900
    assert usage.billable == 150


def test_caching_is_visibly_cheaper() -> None:
    uncached = Usage(input=1000, output=50)
    cached = Usage(input=1000, output=50, cached_input=900)

    assert uncached.billable == 1050
    assert cached.billable == 150
    assert cached.total == uncached.total  # same work, far less billed


def test_usage_adds_up() -> None:
    total = Usage(input=10, output=5) + Usage(input=3, output=2, cached_input=1)
    assert (total.input, total.output, total.cached_input) == (13, 7, 1)


def test_missing_usage_is_zero_not_a_crash() -> None:
    assert profile().read_usage({}).total == 0


# -- response reading -------------------------------------------------------


def test_text_is_read_from_each_shape() -> None:
    assert profile().read_text(
        {"choices": [{"message": {"content": "hi"}}]}
    ) == "hi"
    assert profile(api_mode="anthropic").read_text(
        {"content": [{"type": "text", "text": "hi"}]}
    ) == "hi"
    assert profile(api_mode="responses").read_text({"output_text": "hi"}) == "hi"
    assert profile(api_mode="responses").read_text(
        {"output": [{"content": [{"text": "hi"}]}]}
    ) == "hi"


def test_an_empty_response_reads_as_empty() -> None:
    assert profile().read_text({"choices": []}) == ""


# -- limits are display, not control ----------------------------------------


def test_go_declares_its_rolling_windows_and_that_they_are_unreadable() -> None:
    go = get("opencode-go")

    assert [w[0] for w in go.limits.windows] == ["5 hours", "week", "month"]
    # The console publishes usage; the API does not. This is why budget control
    # is token-based rather than provider-reported.
    assert go.limits.readable is False
    assert "console" in go.limits.note


def test_local_providers_meter_nothing() -> None:
    assert get("ollama").limits.style == "none"


def test_every_registered_provider_declares_its_billing(monkeypatch) -> None:
    for p in all_profiles():
        assert p.access_path in ("api", "plan", "local")
        assert isinstance(p.limits, LimitPolicy)
        if p.access_path == "local":
            assert p.auth_type == "none"


def test_configured_profiles_reflects_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "k")
    monkeypatch.delenv("OPENCODE_ZEN_API_KEY", raising=False)
    names = {p.name for p in configured_profiles()}

    assert "opencode-go" in names
    assert "opencode-zen" not in names
