"""Calling models: token accounting, cooldown, and failover.

These three are tested together because they are one implementation. A 429 is
only survivable because cooldown and failover cooperate, and the budget only
binds because usage is recorded on the same path.
"""

from __future__ import annotations

import httpx
import pytest

from marvi_gateway.identity import IdentityFiles, plan_warning
from marvi_gateway.providers import (
    AllProvidersExhaustedError,
    ProviderCallError,
    ProviderClient,
    Usage,
    get,
)

MESSAGES = [{"role": "system", "content": "You are Marvi."}, {"role": "user", "content": "hi"}]


def responder(status=200, json=None, headers=None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=json or {}, headers=headers or {})

    return httpx.Client(transport=httpx.MockTransport(handler))


def openai_payload(prompt=1000, cached=0, completion=50, text="ok"):
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "prompt_tokens_details": {"cached_tokens": cached},
        },
    }


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "k")


# -- token accounting -------------------------------------------------------


def test_usage_is_recorded_per_provider() -> None:
    client = ProviderClient(http=responder(json=openai_payload()))
    client.call(MESSAGES, provider="openai")

    assert client.usage("openai").input == 1000
    assert client.usage().output == 50


def test_the_budget_sees_the_saving_from_caching() -> None:
    fresh = ProviderClient(http=responder(json=openai_payload(cached=0)))
    fresh.call(MESSAGES, provider="openai")

    warm = ProviderClient(http=responder(json=openai_payload(cached=900)))
    result = warm.call(MESSAGES, provider="openai")

    assert fresh.usage().billable == 1050
    assert warm.usage().billable == 150
    assert result.cached is True


def test_usage_accumulates_across_calls() -> None:
    client = ProviderClient(http=responder(json=openai_payload(prompt=10, completion=5)))
    client.call(MESSAGES, provider="openai")
    client.call(MESSAGES, provider="openai")

    assert client.usage("openai").input == 20


def test_usage_is_broken_down_for_display() -> None:
    client = ProviderClient(http=responder(json=openai_payload(cached=400)))
    client.call(MESSAGES, provider="openai")

    row = client.usage_by_provider()["openai"]
    assert row["cached_input"] == 400
    assert row["billable"] == 650


def test_anthropic_usage_is_read_from_its_own_shape() -> None:
    payload = {
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 100, "cache_read_input_tokens": 900, "output_tokens": 50},
    }
    client = ProviderClient(http=responder(json=payload))
    result = client.call(MESSAGES, provider="anthropic")

    assert result.text == "ok"
    assert result.usage.cached_input == 900
    assert result.usage.billable == 150


# -- cooldown ---------------------------------------------------------------


def test_a_429_stands_the_provider_down_for_the_stated_time() -> None:
    client = ProviderClient(http=responder(status=429, headers={"retry-after": "120"}))
    with pytest.raises(ProviderCallError, match="rate limited"):
        client.call(MESSAGES, provider="openai")

    # Retrying into an exhausted window is how one bad plan becomes a loop.
    #
    # `pytest.approx` rather than `<= 120`: the deadline is monotonic() + 120
    # and the remaining time is that minus monotonic() again, which does not
    # round-trip in floating point -- CI saw 120.00000000000006 and failed by
    # six parts in a hundred trillion. The clock resolution decides whether it
    # happens, so it passes locally and fails on a runner.
    assert client.resting("openai") == pytest.approx(120, abs=5)
    assert "openai" in client.cooldowns()


def test_a_429_without_a_header_still_cools_down() -> None:
    client = ProviderClient(http=responder(status=429))
    with pytest.raises(ProviderCallError):
        client.call(MESSAGES, provider="openai")
    assert client.resting("openai") > 0


def test_a_rejected_credential_cools_down_hard() -> None:
    client = ProviderClient(http=responder(status=401))
    with pytest.raises(ProviderCallError, match="credential"):
        client.call(MESSAGES, provider="openai")

    # A dead key will not fix itself; retrying every minute is pointless.
    assert client.resting("openai") > 3600


def test_a_resting_provider_is_not_called_again() -> None:
    client = ProviderClient(http=responder(status=429, headers={"retry-after": "60"}))
    with pytest.raises(ProviderCallError):
        client.call(MESSAGES, provider="openai")
    with pytest.raises(ProviderCallError, match="cooling down"):
        client.call(MESSAGES, provider="openai")


def test_cooldown_expires() -> None:
    client = ProviderClient()
    client.stand_down("openai", 1, "test")
    assert client.resting("openai") > 0
    # Reading with a later clock clears it.
    assert client.resting("openai", now=client._cooldowns["openai"].until + 1) == 0.0


# -- failover ---------------------------------------------------------------


def test_a_dead_provider_falls_through_to_the_next() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        # Only OpenAI answers; everything tried before it fails.
        if "api.openai.com" not in str(request.url):
            return httpx.Response(500)
        return httpx.Response(200, json=openai_payload(text="from the fallback"))

    client = ProviderClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    result = client.call_with_fallback(MESSAGES)

    # Local is tried first, fails, is cooled down, and a hosted one answers.
    assert result.provider == "openai"
    assert result.text == "from the fallback"
    assert len(calls) >= 2
    assert client.resting("ollama") > 0


def test_everything_exhausted_is_a_clear_error() -> None:
    client = ProviderClient(http=responder(status=500))
    with pytest.raises(AllProvidersExhaustedError):
        client.call_with_fallback(MESSAGES)


def test_candidates_skip_resting_providers() -> None:
    client = ProviderClient()
    before = {p.name for p in client.candidates()}
    client.stand_down("ollama", 300, "test")

    assert "ollama" in before
    assert "ollama" not in {p.name for p in client.candidates()}


def test_a_preferred_provider_goes_first() -> None:
    client = ProviderClient()
    assert client.candidates(preferred="openai")[0].name == "openai"


def test_an_unconfigured_provider_is_refused(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(Exception, match="not configured"):
        ProviderClient(http=responder(json=openai_payload())).call(
            MESSAGES, provider="anthropic"
        )


# -- caching is requested by default ----------------------------------------


def test_caching_is_on_unless_turned_off() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        seen.append(_json.loads(request.content))
        return httpx.Response(200, json=openai_payload())

    client = ProviderClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    client.call(MESSAGES, provider="openai")
    client.call(MESSAGES, provider="openai", cache_prefix=False)

    assert seen[0]["prompt_cache_key"] == "marvi-system"
    assert "prompt_cache_key" not in seen[1]


def test_anthropic_gets_a_breakpoint_on_the_system_block() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        seen.append(_json.loads(request.content))
        return httpx.Response(200, json={"content": [], "usage": {}})

    client = ProviderClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    client.call(MESSAGES, provider="anthropic")

    # Anthropic never caches an unmarked prefix, so forgetting this is a silent
    # full-price bill on every turn.
    assert seen[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


# -- identity ---------------------------------------------------------------


def test_identity_is_absent_until_written(tmp_path) -> None:
    files = IdentityFiles(tmp_path)
    assert files.read().present is False
    assert files.compose("Do the thing.") == "Do the thing."


def test_identity_composes_ahead_of_the_task(tmp_path) -> None:
    files = IdentityFiles(tmp_path)
    files.write_soul("You are terse.")
    files.write_user("Shereef. Works late.")
    prompt = files.compose("Answer the question.")

    assert prompt.index("You are terse.") < prompt.index("Shereef")
    assert prompt.index("Shereef") < prompt.index("Answer the question.")


def test_user_context_is_labelled_as_context_not_instruction(tmp_path) -> None:
    files = IdentityFiles(tmp_path)
    files.write_user("Shereef.")
    assert "not an instruction" in files.compose()


def test_the_budget_is_enforced_not_hoped_for(tmp_path) -> None:
    files = IdentityFiles(tmp_path, budget_tokens=50)
    files.write_soul("\n".join(f"soul line {i}" for i in range(500)))
    files.write_user("\n".join(f"user line {i}" for i in range(500)))
    identity = files.read()

    assert identity.truncated is True
    # Every token here is paid on every turn, including the voice path.
    assert identity.tokens <= 50


def test_a_short_identity_is_not_truncated(tmp_path) -> None:
    files = IdentityFiles(tmp_path)
    files.write_soul("Terse.")
    files.write_user("Shereef.")
    assert files.read().truncated is False


def test_status_reports_what_the_page_needs(tmp_path) -> None:
    files = IdentityFiles(tmp_path)
    files.write_soul("Terse.")
    status = files.status()

    assert status["soul_present"] is True
    assert status["user_present"] is False
    assert status["budget"] > 0


# -- plan terms --------------------------------------------------------------


def test_plan_providers_carry_a_warning_and_api_providers_do_not() -> None:
    assert plan_warning(get("codex")) is not None
    assert plan_warning(get("claude-code")) is not None
    assert plan_warning(get("opencode-go")) is not None
    assert plan_warning(get("openai")) is None
    assert plan_warning(get("ollama")) is None


def test_the_warning_says_what_the_actual_risk_is() -> None:
    warning = plan_warning(get("codex")) or ""
    # Vague warnings get clicked through; name the consequence.
    assert "terms of service" in warning
    assert "suspension" in warning


def test_usage_arithmetic() -> None:
    assert (Usage(input=10, output=5) + Usage(input=1, output=1)).total == 17
