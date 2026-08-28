"""Calling models: token accounting, cooldown, and failover.

These three are tested together because they are one implementation. A 429 is
only survivable because cooldown and failover cooperate, and the budget only
binds because usage is recorded on the same path.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.app import create_app
from marvi_gateway.identity import IdentityFiles, plan_warning
from marvi_gateway.providers import (
    AllProvidersExhaustedError,
    ProviderCallError,
    ProviderClient,
    Usage,
    get,
)
from marvi_gateway.runtime import RuntimeStore
from marvi_gateway.tools import ToolRegistry

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


def test_model_calls_log_route_latency_and_usage_without_prompt_content(caplog) -> None:
    client = ProviderClient(http=responder(json=openai_payload(prompt=12, completion=3)))

    with caplog.at_level(logging.INFO, logger="marvi_gateway.providers.client"):
        client.call(MESSAGES, provider="openai", job="aux", model="gpt-5.2-mini")

    started = next(record for record in caplog.records if record.message == "model call started")
    completed = next(
        record for record in caplog.records if record.message == "model call completed"
    )
    assert started.marvi_job == "aux"
    assert started.marvi_provider == "openai"
    assert started.marvi_model == "gpt-5.2-mini"
    assert completed.marvi_billable_tokens == 15
    rendered = " ".join(record.getMessage() for record in caplog.records)
    assert "You are Marvi" not in rendered


def test_auxiliary_jobs_follow_the_main_model() -> None:
    """They used to run on a per-provider `default_aux_model`, so every
    background job went to `google/gemini-3.5-flash-lite` while the Models
    page said, of every role, "Auto — uses your main model" and the user had
    chosen DeepSeek. The page was describing what anyone would assume; the
    code did something else.

    A cheaper model for a background job is a good idea and is what the
    role pickers are for. What it may not be is silent.
    """
    requested: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        requested.update(json.loads(request.content))
        return httpx.Response(200, json=openai_payload())

    client = ProviderClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    client.call(MESSAGES, provider="openai", job="aux")

    # What was asked for is the main model. What came back is whatever the
    # fixture says the provider answered with, which is not the same claim.
    assert requested["model"] == "gpt-5.2"


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


def test_a_bad_request_does_not_cool_the_provider_down() -> None:
    """A 400 is our request, not their availability.

    It cooled OpenRouter down for five minutes, every time, over a background
    verdict nobody was waiting for -- and the conversation then fell through to
    a provider whose key was dead and ended at "No provider is available".
    """
    client = ProviderClient(
        http=responder(status=400, json={"error": {"message": "tools not supported"}})
    )
    with pytest.raises(ProviderCallError, match="rejected the request"):
        client.call(MESSAGES, provider="openai")

    assert client.resting("openai") == 0.0
    assert "openai" not in client.cooldowns()


def test_a_bad_request_carries_what_the_provider_said() -> None:
    """httpx's own message is "Client error '400 Bad Request'" and nothing else."""
    client = ProviderClient(
        http=responder(status=400, json={"error": {"message": "tools not supported"}})
    )
    with pytest.raises(ProviderCallError, match="tools not supported"):
        client.call(MESSAGES, provider="openai")


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


def test_a_dead_provider_falls_through_to_the_next(monkeypatch) -> None:
    from marvi_gateway.providers import get

    monkeypatch.setenv(get("ollama").enabled_setting(), "true")
    monkeypatch.delenv("MARVI_PROVIDER", raising=False)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        # Only OpenAI answers; everything tried before it fails.
        if "api.openai.com" not in str(request.url):
            return httpx.Response(500)
        return httpx.Response(200, json=openai_payload(text="from the fallback"))

    client = ProviderClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    result = client.call_with_fallback(MESSAGES)

    # A connected local provider is tried first, fails, is cooled down, and a
    # hosted one answers. Fallback still works -- what changed is that an
    # unconnected local provider is not in the list to be tried at all.
    assert result.provider == "openai"
    assert result.text == "from the fallback"
    assert len(calls) >= 2
    assert client.resting("ollama") > 0


def test_everything_exhausted_is_a_clear_error() -> None:
    client = ProviderClient(http=responder(status=500))
    with pytest.raises(AllProvidersExhaustedError):
        client.call_with_fallback(MESSAGES)


def test_candidates_skip_resting_providers(monkeypatch) -> None:
    from marvi_gateway.providers import get

    # Connected first: a local provider is no longer a candidate merely for
    # having a default URL.
    monkeypatch.setenv(get("ollama").enabled_setting(), "true")
    monkeypatch.delenv("MARVI_PROVIDER", raising=False)

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


# -- the selected provider ---------------------------------------------------


def test_the_selected_provider_is_tried_first(monkeypatch) -> None:
    """MARVI_PROVIDER is the standing choice, and it was being ignored.

    `candidates` sorts local-first, so a machine with LM Studio configured but
    not running tried it, waited for the connection to be refused, tried
    Ollama, waited again, and only then reached the provider the user had
    actually picked. Voice never recovered at all: it takes the first usable
    candidate and got a local endpoint with no model name.
    """
    monkeypatch.setenv("MARVI_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("MARVI_LMSTUDIO_URL", "http://127.0.0.1:1234/v1")

    order = [p.name for p in ProviderClient().candidates()]

    assert order[0] == "openrouter"


def test_an_explicit_choice_still_beats_the_setting(monkeypatch) -> None:
    """The composer's per-turn picker has to win over the standing default."""
    monkeypatch.setenv("MARVI_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    order = [p.name for p in ProviderClient().candidates("openai")]

    assert order[0] == "openai"


def test_a_setting_naming_a_provider_that_does_not_exist_is_ignored(monkeypatch) -> None:
    """A stale setting is not a reason to stop answering."""
    monkeypatch.setenv("MARVI_PROVIDER", "a-provider-that-was-removed")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    order = [p.name for p in ProviderClient().candidates()]

    assert "openrouter" in order


@pytest.mark.asyncio
async def test_soul_and_user_both_reach_the_voice_worker(tmp_path, monkeypatch) -> None:
    """`/context` is the only way SOUL.md gets to the spoken surface.

    The Agent builds its own instructions in a separate process, so anything
    the Gateway holds reaches it through this route or not at all -- and the
    first time that was true of USER.md, Marvi did not know her own name and
    wrote it into memory five times instead, once per mishearing.

    Both files are checked here because the failure is silent in exactly the
    same way: the voice path keeps working, and answers as though the person
    in front of it were a stranger.
    """
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    files = IdentityFiles(tmp_path)
    files.write_soul("# Marvi\n\nYou stay running. Short. One thought per turn.")
    files.write_user("Shereef, who builds Marvi.")

    app = create_app(
        version="0.1.0-test", runtime=RuntimeStore(tmp_path / "r.db"), tools=ToolRegistry()
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as c:
        blocks = (await c.get("/context")).json()["blocks"]

    joined = "\n".join(blocks)
    assert "One thought per turn" in joined, "SOUL.md never reached the prompt"
    assert "Shereef, who builds Marvi." in joined, "USER.md never reached the prompt"
    # Labelled, so a block of prose about a person is not read as a note.
    assert "true on every turn" in joined
