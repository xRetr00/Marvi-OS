"""Listing a provider's models.

The provider's own response is faked, because that is somebody else's server;
everything else -- the three envelope shapes, the per-model effort rule, the
caching -- is real, because that is the part that decides what the picker shows.
"""

from __future__ import annotations

import httpx
import pytest

from marvi_gateway.providers import catalog, get


@pytest.fixture(autouse=True)
def empty_cache():
    catalog.forget()
    yield
    catalog.forget()


def responder(payload, status: int = 200, seen: list | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        return httpx.Response(status, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_an_openai_shaped_list_becomes_cards() -> None:
    profile = get("openai")
    http = responder({"data": [{"id": "gpt-5"}, {"id": "gpt-5-mini"}]})

    cards = catalog.fetch(profile, http=http)

    assert [card.id for card in cards] == ["gpt-5", "gpt-5-mini"]
    assert cards[0].provider == "openai"


def test_an_anthropic_display_name_is_used_as_the_label() -> None:
    profile = get("anthropic")
    http = responder({"data": [{"id": "claude-sonnet-5", "display_name": "Claude Sonnet 5"}]})

    (card,) = catalog.fetch(profile, http=http)

    assert card.id == "claude-sonnet-5"
    assert card.name == "Claude Sonnet 5"


def test_openrouter_pricing_is_reported_per_million() -> None:
    """Per-token figures are unreadable in a table; the picker shows dollars."""
    profile = get("openrouter")
    http = responder(
        {
            "data": [
                {
                    "id": "anthropic/claude-sonnet-5",
                    "name": "Claude Sonnet 5",
                    "context_length": 200_000,
                    "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                    "supported_parameters": ["reasoning", "tools"],
                    "architecture": {"input_modalities": ["text", "image"]},
                }
            ]
        }
    )

    (card,) = catalog.fetch(profile, http=http)

    assert card.prompt_per_million == 3.0
    assert card.completion_per_million == 15.0
    assert card.context == 200_000
    assert card.vision is True


def test_effort_is_offered_only_for_models_that_reason() -> None:
    """The reason effort cannot be a provider-wide setting for a gateway.

    OpenRouter fronts both kinds under one credential, so a provider-level
    answer would offer an effort control on models that ignore it.
    """
    profile = get("openrouter")
    http = responder(
        {
            "data": [
                {"id": "thinks", "supported_parameters": ["reasoning", "tools"]},
                {"id": "does-not", "supported_parameters": ["tools"]},
            ]
        }
    )

    plain, thinks = sorted(catalog.fetch(profile, http=http), key=lambda c: c.id)

    assert plain.id == "does-not"
    assert plain.efforts == ()
    assert plain.reasons is False
    assert thinks.efforts == profile.reasoning.levels
    assert thinks.reasons is True


def test_a_provider_that_does_not_publish_parameters_uses_its_own_policy() -> None:
    """Anthropic's list does not mark reasoning per model, and it is uniform."""
    profile = get("codex")
    http = responder({"data": [{"id": "gpt-5-codex"}]})

    (card,) = catalog.fetch(profile, http=http)

    assert card.efforts == profile.reasoning.levels


def test_an_unreachable_provider_returns_nothing_rather_than_raising() -> None:
    """This feeds a picker. A provider being down leaves the field typeable."""
    profile = get("openai")
    http = responder({"error": "nope"}, status=500)

    assert catalog.fetch(profile, http=http) == []


def test_a_nonsense_payload_does_not_crash_the_page() -> None:
    profile = get("openai")

    assert catalog.fetch(profile, http=responder({"data": "not a list"})) == []
    assert catalog.fetch(profile, http=responder({"data": [{"no": "id"}]})) == []


def test_the_list_is_fetched_once_and_then_cached() -> None:
    profile = get("openai")
    seen: list[str] = []
    http = responder({"data": [{"id": "gpt-5"}]}, seen=seen)

    catalog.models(profile, http=http)
    catalog.models(profile, http=http)

    assert len(seen) == 1


def test_refresh_asks_again() -> None:
    profile = get("openai")
    seen: list[str] = []
    http = responder({"data": [{"id": "gpt-5"}]}, seen=seen)

    catalog.models(profile, http=http)
    catalog.models(profile, http=http, refresh=True)

    assert len(seen) == 2


def test_a_failed_refresh_keeps_the_last_good_list() -> None:
    """A provider blipping must not look like a provider with no models."""
    profile = get("openai")
    catalog.models(profile, http=responder({"data": [{"id": "gpt-5"}]}))

    still = catalog.models(profile, http=responder({}, status=503), refresh=True)

    assert [card.id for card in still] == ["gpt-5"]


def test_a_call_can_name_its_own_model_without_changing_the_default(configured) -> None:
    """The composer's picker is "try this model here", not "change my settings".

    An override that persisted would make the last thing anyone experimented
    with the new default for everything -- voice, mind, vision included.
    """
    from marvi_gateway.providers import ProviderClient

    profile = configured("openai")
    default_model = profile.model_for("main")
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        asked.append(json.loads(request.content)["model"])
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    client = ProviderClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    messages = [{"role": "user", "content": "hi"}]

    client.call(messages, provider=profile, model="a-different-model")
    client.call(messages, provider=profile)

    assert asked == ["a-different-model", default_model]
    assert profile.model_for("main") == default_model


# -- the endpoint ------------------------------------------------------------
#
# Tested separately from the catalog, because the first version of it passed
# every catalog test above and still returned a 500: it called a registry
# function by a name that does not exist. Ruff caught that, not the tests.


def test_the_models_endpoint_answers() -> None:
    from fastapi.testclient import TestClient

    from marvi_gateway.app import create_app

    with TestClient(create_app()) as client:
        response = client.get("/models")

    assert response.status_code == 200
    assert isinstance(response.json()["providers"], list)


def test_asking_for_one_provider_narrows_the_answer() -> None:
    from fastapi.testclient import TestClient

    from marvi_gateway.app import create_app

    with TestClient(create_app()) as client:
        response = client.get("/models", params={"provider": "openrouter"})

    assert response.status_code == 200
    names = {row["provider"] for row in response.json()["providers"]}
    assert names <= {"openrouter"}


def test_asking_for_a_provider_that_does_not_exist_says_so() -> None:
    from fastapi.testclient import TestClient

    from marvi_gateway.app import create_app

    with TestClient(create_app()) as client:
        response = client.get("/models", params={"provider": "not-a-provider"})

    assert response.status_code == 404


# -- measurement -------------------------------------------------------------


def test_a_chat_turn_is_recorded_for_latency(tmp_path, monkeypatch, configured) -> None:
    """The seam existed and was connected to nothing.

    `/latency` sat at zero samples through every conversation, on both
    surfaces, because the wrapper was written and never called. A baseline
    nobody records is not a baseline, and the whole providers phase is gated on
    comparing against one -- so the wiring itself is what this asserts, not the
    numbers.
    """
    from marvi_gateway import latency
    from marvi_gateway.chat import Chat, ChatStore
    from marvi_gateway.providers import ProviderClient

    configured()

    recording = tmp_path / "latency.jsonl"
    monkeypatch.setattr(latency, "recording_path", lambda: recording)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            },
        )

    chat = Chat(
        store=ChatStore(tmp_path / "chat.sqlite3"),
        client=ProviderClient(http=httpx.Client(transport=httpx.MockTransport(handler))),
    )

    turn = chat.send("hello", provider="openai")

    assert turn.error == ""
    summary = latency.summarise("chat")
    assert summary["samples"] == 1


def test_the_recorded_turn_names_the_provider_that_answered(tmp_path, monkeypatch, configured) -> None:
    """Not the one that was asked for.

    Fallback means those differ exactly when it matters most -- a sample
    attributed to a provider that never ran is worse than no sample.
    """
    from marvi_gateway import latency
    from marvi_gateway.chat import Chat, ChatStore
    from marvi_gateway.providers import ProviderClient

    configured()

    monkeypatch.setattr(latency, "recording_path", lambda: tmp_path / "latency.jsonl")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    chat = Chat(
        store=ChatStore(tmp_path / "chat.sqlite3"),
        client=ProviderClient(http=httpx.Client(transport=httpx.MockTransport(handler))),
    )
    turn = chat.send("hi", provider="openai")

    rows = [
        __import__("json").loads(line)
        for line in (tmp_path / "latency.jsonl").read_text().splitlines()
        if line.strip()
    ]

    # The provider that answered, not the one that was asked for: fallback
    # makes those differ exactly when it matters, and a sample attributed to a
    # provider that never ran is worse than no sample.
    assert rows[-1]["provider"] == turn.provider
    assert rows[-1]["surface"] == "chat"
    # Chat does not stream, so there is genuinely no first token to time. None
    # rather than a number copied from the total, which would be
    # indistinguishable from a real measurement in the summary.
    assert rows[-1]["first_token_ms"] is None
    assert rows[-1]["total_ms"] > 0


# -- effort as a setting -----------------------------------------------------


def test_a_configured_effort_reaches_the_request(monkeypatch, configured) -> None:
    """Effort was a parameter nothing ever set.

    `call` accepted one and no caller passed it, so a provider's reasoning
    settings were unreachable from the UI and every call ran at whatever the
    provider's own default happened to be.
    """
    import json

    from marvi_gateway.providers import ProviderClient

    profile = configured("openai")
    monkeypatch.setenv(profile.effort_setting(), "high")
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    client = ProviderClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    client.call([{"role": "user", "content": "hi"}], provider=profile)

    assert json.dumps(bodies[0]).find("high") >= 0


def test_an_effort_the_provider_does_not_accept_is_not_sent(monkeypatch) -> None:
    profile = get("openai")
    monkeypatch.setenv(profile.effort_setting(), "extreme")

    assert profile.effort_for() in (*profile.reasoning.levels, None)
    assert profile.effort_for() != "extreme"


def test_a_provider_that_does_not_reason_has_no_effort_setting() -> None:
    """So the UI has nothing to offer, rather than a control that does nothing."""
    assert get("anthropic").effort_setting() == ""
    assert get("anthropic").effort_for() is None


# -- one answer, not two -----------------------------------------------------


def test_the_voice_readout_names_what_the_agent_will_actually_use(monkeypatch) -> None:
    """They were two different resolvers and they disagreed.

    `/runtime`'s readout took the first configured provider with no further
    checks, so it named LM Studio -- configured by having a URL, not running,
    and with no model set -- while `/providers/voice` handed the Agent
    OpenRouter. The page said one thing and the turn used another. It only ever
    looked right when LM Studio happened to be in cooldown.
    """
    from fastapi.testclient import TestClient

    from marvi_gateway.app import create_app

    # A local provider that is "configured" only in the sense of having a URL
    # nothing is listening on -- exactly the shape that won before.
    monkeypatch.setenv("MARVI_LMSTUDIO_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("MARVI_OPENROUTER_MODEL", "vendor/some-model")

    with TestClient(create_app()) as client:
        readout = client.get("/runtime").json()["model"]["llm"]
        resolved = client.get("/providers/voice")

    if resolved.status_code == 503:
        # Nothing usable at all is a coherent answer, as long as the readout
        # agrees rather than naming something.
        assert readout == ""
        return

    # Comparing the model rather than the provider label: the readout carries
    # a display name ("OpenRouter") and the resolver a registry name
    # ("openrouter"), and the model id is the part that is identical in both.
    assert resolved.json()["model"] in readout


def test_a_local_endpoint_with_no_model_is_never_named() -> None:
    """It cannot answer, so naming it in the readout is a lie either way."""
    from marvi_gateway.providers import get

    lmstudio = get("lmstudio")

    # The precondition for the original bug: configured, but nothing to call.
    if lmstudio.configured() and not lmstudio.model_for("main"):
        from fastapi.testclient import TestClient

        from marvi_gateway.app import create_app

        with TestClient(create_app()) as client:
            readout = client.get("/runtime").json()["model"]["llm"]

        assert "lm studio" not in readout.lower()


# -- a provider is connected when it answers ---------------------------------


def test_a_local_provider_is_not_connected_by_having_a_url(monkeypatch) -> None:
    """The bug behind every "LM Studio" surprise in this project.

    Local providers ship with a default base URL, and having one used to count
    as configured. So LM Studio and Ollama were permanently connected on a
    machine where neither was running, won the fallback ordering, and answered
    turns with nothing behind them -- which is how a voice session resolved to
    "LM Studio /" with no model at all.
    """
    profile = get("lmstudio")
    monkeypatch.delenv(profile.enabled_setting(), raising=False)

    assert profile.base_url(), "it still has a URL"
    assert profile.configured() is False, "but a URL is not a connection"


def test_connecting_a_local_provider_makes_it_configured(monkeypatch) -> None:
    profile = get("ollama")
    monkeypatch.setenv(profile.enabled_setting(), "true")

    assert profile.configured() is True


def test_the_selected_provider_is_the_only_candidate(monkeypatch) -> None:
    """Locked, not merely preferred.

    Keeping the others behind the chosen one meant a turn could quietly be
    answered by something never picked -- replies coming back from LM Studio
    while the page said OpenRouter, and the same question answered by a
    different model each time.
    """
    from marvi_gateway.providers import ProviderClient

    monkeypatch.setenv("MARVI_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv(get("lmstudio").enabled_setting(), "true")

    assert [p.name for p in ProviderClient().candidates()] == ["openrouter"]


def test_a_selection_that_is_not_configured_does_not_strand_marvi(monkeypatch) -> None:
    """A stale choice is not a reason to stop answering."""
    from marvi_gateway.providers import ProviderClient

    monkeypatch.setenv("MARVI_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    names = [p.name for p in ProviderClient().candidates()]

    assert "openrouter" in names


def test_the_context_window_comes_from_the_provider() -> None:
    """Rather than being assumed, or left for the plugin to maximise."""
    profile = get("openrouter")
    http = responder(
        {"data": [{"id": "vendor/model", "context_length": 128000}]}
    )

    (card,) = catalog.fetch(profile, http=http)

    assert card.context == 128000
