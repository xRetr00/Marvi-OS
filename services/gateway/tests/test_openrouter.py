"""OpenRouter upstream routing.

OpenRouter is a gateway: one model name resolves to several upstream providers
with different prices and different times to first token. By default it picks
the cheapest reliable one, which for voice is the wrong default — the words
either start quickly or Marvi feels slow.
"""

from __future__ import annotations

import pytest

from marvi_gateway.providers import get
from marvi_gateway.providers.openrouter import POLICIES, Route, endpoints, route_for


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in (
        "MARVI_OPENROUTER_ROUTE",
        "MARVI_OPENROUTER_ROUTE_VOICE",
        "MARVI_OPENROUTER_ROUTE_MAIN",
        "MARVI_OPENROUTER_PROVIDERS",
        "MARVI_OPENROUTER_IGNORE",
        "MARVI_OPENROUTER_PIN",
    ):
        monkeypatch.delenv(name, raising=False)


def test_voice_asks_for_the_fastest_upstream_by_default() -> None:
    """The whole reason this exists. Cheapest is frequently not fastest."""
    assert route_for("voice").as_body() == {"sort": "latency"}


def test_other_jobs_leave_the_choice_to_openrouter() -> None:
    # Sending nothing is not the same as sending an empty preference object.
    assert route_for("main").as_body() == {}


def test_a_job_can_be_set_apart_from_the_rest(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_OPENROUTER_ROUTE", "cheapest")
    monkeypatch.setenv("MARVI_OPENROUTER_ROUTE_VOICE", "fastest")

    assert route_for("main").as_body() == {"sort": "price"}
    assert route_for("voice").as_body() == {"sort": "latency"}


def test_an_unknown_policy_falls_back_rather_than_being_sent(monkeypatch) -> None:
    # A typo must not reach OpenRouter as a sort it does not understand.
    monkeypatch.setenv("MARVI_OPENROUTER_ROUTE", "quickest")

    assert route_for("voice").as_body() == {"sort": "latency"}


def test_named_upstreams_are_ordered_and_still_allowed_to_fall_back(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_OPENROUTER_PROVIDERS", "groq, cerebras")

    body = route_for("voice").as_body()

    assert body["order"] == ["groq", "cerebras"]
    # Pinning without fallback turns an upstream outage into Marvi's outage,
    # so it is never the default.
    assert "allow_fallbacks" not in body


def test_pinning_is_explicit(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_OPENROUTER_PROVIDERS", "groq")
    monkeypatch.setenv("MARVI_OPENROUTER_PIN", "1")

    assert route_for("voice").as_body()["allow_fallbacks"] is False


def test_an_upstream_can_be_ruled_out(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_OPENROUTER_IGNORE", "slow-one")

    assert route_for("voice").as_body()["ignore"] == ["slow-one"]


def test_every_policy_maps_to_something_openrouter_accepts() -> None:
    accepted = {"", "price", "latency", "throughput"}
    for value in POLICIES.values():
        assert value in accepted


# -- only the gateway gets routed --------------------------------------------


def test_the_route_reaches_the_request_body() -> None:
    body = get("openrouter").build_request([{"role": "user", "content": "hi"}], job="voice")

    assert body["provider"] == {"sort": "latency"}


def test_a_direct_provider_is_never_sent_a_provider_block() -> None:
    """`provider` is OpenRouter's field. Sending it to OpenAI is a 400 waiting
    to happen, and to a local server it is noise."""
    for name in ("openai", "anthropic", "ollama"):
        profile = get(name)
        if profile is None:
            continue
        body = profile.build_request([{"role": "user", "content": "hi"}], job="voice")
        assert "provider" not in body, name


# -- reading the upstreams ---------------------------------------------------


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self, payload):
        self._payload = payload
        self.url = ""

    def get(self, url, headers=None):
        self.url = url
        return FakeResponse(self._payload)


def test_upstreams_are_read_with_the_numbers_that_decide_between_them() -> None:
    http = FakeHttp(
        {
            "data": {
                "endpoints": [
                    {
                        "tag": "groq",
                        "provider_name": "Groq",
                        "context_length": 128000,
                        "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
                        "latency_last_30m": 210.4,
                        "throughput_last_30m": 480.0,
                        "uptime_last_30m": 99.9,
                    }
                ]
            }
        }
    )

    row = endpoints("openai/gpt-4o-mini", http=http)[0]

    assert row["slug"] == "groq"
    assert row["name"] == "Groq"
    # Per million: the per-token figures are unreadable in a table.
    assert row["prompt_per_million"] == 0.15
    assert row["completion_per_million"] == 0.6
    assert row["latency_ms"] == 210.4


def test_a_missing_measurement_is_none_rather_than_zero() -> None:
    """Checked against the live API: of the nine endpoints serving Claude
    Sonnet 5, all nine are priced and none publish latency. Zero would read as
    instant."""
    http = FakeHttp(
        {
            "data": {
                "endpoints": [
                    {
                        "tag": "anthropic",
                        "provider_name": "Anthropic",
                        "pricing": {"prompt": "0.000003"},
                        "latency_last_30m": None,
                        "throughput_last_30m": None,
                    }
                ]
            }
        }
    )

    row = endpoints("anthropic/claude-sonnet-5", http=http)[0]

    assert row["latency_ms"] is None
    assert row["throughput"] is None
    assert row["prompt_per_million"] == 3.0


def test_a_local_model_name_is_not_asked_about() -> None:
    # OpenRouter ids are vendor/model. A bare name is a local server's.
    http = FakeHttp({"data": {"endpoints": [{"tag": "x"}]}})

    assert endpoints("llama3", http=http) == []
    assert http.url == ""


def test_a_listing_failure_is_empty_rather_than_an_exception() -> None:
    class Broken:
        def get(self, url, headers=None):
            raise RuntimeError("offline")

    # A dropdown that cannot be filled is not a reason to fail the page.
    assert endpoints("openai/gpt-4o-mini", http=Broken()) == []


def test_an_empty_route_sends_nothing() -> None:
    assert Route().as_body() == {}
