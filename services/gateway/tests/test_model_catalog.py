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


def test_a_call_can_name_its_own_model_without_changing_the_default() -> None:
    """The composer's picker is "try this model here", not "change my settings".

    An override that persisted would make the last thing anyone experimented
    with the new default for everything -- voice, mind, vision included.
    """
    from marvi_gateway.providers import ProviderClient

    profile = get("openai")
    configured = profile.model_for("main")
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

    assert asked == ["a-different-model", configured]
    assert profile.model_for("main") == configured
