"""Proactive speech and LLM deliberation.

The real PocketTTS model is exercised in one marked test; everything else uses
fakes so the failure paths are deliberate rather than incidental.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from marvi_gateway.announce import Announcer, announce_enabled
from marvi_gateway.deliberate import Deliberator, _parse, deliberator_from_env
from marvi_gateway.journal import EventJournal
from marvi_gateway.mind import Mind
from marvi_gateway.policy import Verdict
from marvi_gateway.providers import ProviderClient

NOON = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def journal(tmp_path):
    j = EventJournal(tmp_path / "journal.sqlite3")
    yield j
    j.close()


class FakeAnnouncer:
    def __init__(self, works=True):
        self.works = works
        self.said: list[str] = []

    def speak(self, text):
        self.said.append(text)
        return {"played": True} if self.works else {"played": False, "error": "no output"}


# -- speech ----------------------------------------------------------------


def test_announcements_are_on_by_default_and_can_be_switched_off(monkeypatch) -> None:
    monkeypatch.delenv("MARVI_ANNOUNCE", raising=False)
    assert announce_enabled() is True
    monkeypatch.setenv("MARVI_ANNOUNCE", "off")
    assert announce_enabled() is False


def test_a_speak_decision_reaches_the_announcer(journal) -> None:
    journal.append("room", "alarm_started", "Alarm going off", trusted=True)
    announcer = FakeAnnouncer()
    mind = Mind(journal, announcer=announcer)
    mind.tick(now=NOON)

    assert announcer.said == ["Alarm going off"]
    assert mind.why()[0]["outcome"].startswith("spoke:")


def test_losing_the_voice_falls_back_to_the_island(journal) -> None:
    journal.append("room", "alarm_started", "Alarm going off", trusted=True)
    mind = Mind(journal, announcer=FakeAnnouncer(works=False))
    result = mind.tick(now=NOON)

    # The decision survives even though the speech did not.
    assert result["decisions"][0]["surface"] == "island"
    assert "speech unavailable" in mind.why()[0]["detail"]


def test_a_quieter_surface_never_speaks(journal) -> None:
    journal.append("accounts", "email", "Email: hi", trusted=False)
    announcer = FakeAnnouncer()
    Mind(journal, announcer=announcer).tick(now=NOON)

    # Email tops out at the Island, so nothing is spoken.
    assert announcer.said == []


def test_empty_text_is_refused_rather_than_synthesised() -> None:
    result = Announcer().speak("   ")
    assert result["played"] is False
    assert "nothing to say" in result["error"]


def test_room_welcome_reaches_the_same_standalone_announcer(journal) -> None:
    journal.append("room", "room_welcome", "Welcome home, Ada.", trusted=True)
    announcer = FakeAnnouncer()

    Mind(journal, announcer=announcer).tick(now=NOON)

    # The routing is what this pins: a room welcome reaches the announcer.
    # The words are `voicing`'s now -- the summary is written for a journal
    # and reading one aloud is what made her sound like a dashboard -- so this
    # asserts that something welcoming was said, not which phrasing won.
    assert len(announcer.said) == 1
    assert "Welcome" in announcer.said[0] or "you are home" in announcer.said[0]


@pytest.mark.browser
def test_pocket_tts_really_synthesises_on_cpu() -> None:
    """Marked because it loads a real model; skipped when unavailable."""
    pytest.importorskip("pocket_tts")
    pcm, rate = Announcer().synthesize("Testing one two three.")

    assert rate == 24_000
    assert len(pcm) > rate  # at least half a second of 16-bit audio
    assert len(pcm) % 2 == 0


# -- deliberation ----------------------------------------------------------


def verdict(surface="speak"):
    return Verdict(True, surface, "allowed", "ceiling speak")


def event():
    return {"source": "room", "kind": "alarm_started", "summary": "Alarm",
            "payload": {}, "trusted": True, "id": 1}


def deliberator(handler, usage=None) -> Deliberator:
    """A Deliberator wired to a fake OpenAI-compatible provider."""
    client = ProviderClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    return Deliberator(client=client, preferred="openai")


def reply(text: str, prompt=20, completion=10) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    })


def test_no_provider_keeps_the_mind_deterministic(monkeypatch) -> None:
    # Nothing configured anywhere, including the local servers.
    monkeypatch.setattr("marvi_gateway.deliberate.configured_profiles", lambda: [])
    assert deliberator_from_env() is None


def test_a_configured_provider_is_used(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    assert deliberator_from_env() is not None


def test_the_model_can_choose_silence(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    d = deliberator(lambda request: reply('{"worth_it": false, "say": ""}'))
    surface, _detail, tokens = d(event(), verdict())

    assert surface == "silent"
    assert tokens == 30


def test_the_model_phrases_the_sentence_but_keeps_the_surface(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")

    def handler(request):
        body = json.loads(request.content)
        # The event content must arrive enveloped and labelled untrusted-safe.
        assert "EXTERNAL DATA" in body["messages"][1]["content"]
        return reply('{"worth_it": true, "say": "Your alarm is going off."}')

    d = deliberator(handler)
    surface, detail, _ = d(event(), verdict("speak"))

    assert surface == "speak"
    assert detail == "Your alarm is going off."


def test_mind_role_routes_to_the_configured_auxiliary_model(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("MARVI_AUX_MIND", "openai/gpt-5.2-mini")

    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "gpt-5.2-mini"
        return reply('{"worth_it": true, "say": "Auxiliary answered."}')

    d = deliberator(handler)
    assert d(event(), verdict("island"))[1] == "Auxiliary answered."
    assert d.last_provider == "openai"
    assert d.last_model == "gpt-5.2-mini"


def test_a_provider_failure_falls_back_to_the_policy_verdict(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    d = deliberator(lambda request: httpx.Response(500))
    surface, _detail, tokens = d(event(), verdict("island"))

    assert surface == "island"
    assert tokens == 0  # a failed thought is not billed


def test_unparseable_output_falls_back_without_crashing(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    d = deliberator(lambda request: reply("I think maybe?"))
    assert d(event(), verdict("island"))[0] == "island"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"worth_it": true, "say": "hi"}', (True, "hi")),
        ('```json\n{"worth_it": false, "say": ""}\n```', (False, "")),
        ('Sure! {"worth_it": true, "say": "ok"} hope that helps', (True, "ok")),
        ("no json here", None),
        ('{"nope": 1}', None),
    ],
)
def test_output_parsing_tolerates_chatty_models(raw, expected) -> None:
    assert _parse(raw) == expected


def test_deliberation_tokens_are_charged_to_the_budget(journal, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    journal.append("room", "alarm_started", "Alarm", trusted=True)

    d = deliberator(lambda request: reply('{"worth_it": true, "say": "Alarm."}'))
    mind = Mind(journal, deliberate=d, announcer=FakeAnnouncer())
    mind.tick(now=NOON)

    assert mind.why()[0]["provider"].startswith("openai/")
    assert mind.why()[0]["tokens"] == 30


def test_caching_reduces_what_the_budget_is_charged(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")

    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"worth_it": false, "say": ""}'}}],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 10,
                "prompt_tokens_details": {"cached_tokens": 950},
            },
        })

    # The system prompt is identical on every tick, so it should be cached and
    # the budget should see the saving rather than a flat per-call estimate.
    assert deliberator(handler)(event(), verdict())[2] == 60
