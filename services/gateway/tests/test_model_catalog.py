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


def test_a_chat_turn_is_recorded_for_latency(tmp_path, monkeypatch) -> None:
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


def test_the_recorded_turn_names_the_provider_that_answered(tmp_path, monkeypatch) -> None:
    """Not the one that was asked for.

    Fallback means those differ exactly when it matters most -- a sample
    attributed to a provider that never ran is worse than no sample.
    """
    from marvi_gateway import latency
    from marvi_gateway.chat import Chat, ChatStore
    from marvi_gateway.providers import ProviderClient

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
