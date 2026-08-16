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
        return {"published": True} if self.works else {"published": False, "error": "no room"}


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
    assert result["published"] is False
    assert "nothing to say" in result["error"]


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


def test_no_provider_keeps_the_mind_deterministic(monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "")
    assert deliberator_from_env() is None


def test_a_configured_provider_is_used(monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "key")
    assert deliberator_from_env() is not None


def test_the_model_can_choose_silence() -> None:
    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"worth_it": false, "say": ""}'}}]
        })

    d = Deliberator(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    surface, _detail, cost = d(event(), verdict())

    assert surface == "silent"
    assert cost > 0


def test_the_model_phrases_the_sentence_but_keeps_the_surface() -> None:
    def handler(request):
        body = json.loads(request.content)
        # The event content must arrive enveloped and labelled untrusted-safe.
        assert "EXTERNAL DATA" in body["messages"][1]["content"]
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"worth_it": true, "say": "Your alarm is going off."}'}}]
        })

    d = Deliberator(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    surface, detail, _ = d(event(), verdict("speak"))

    assert surface == "speak"
    assert detail == "Your alarm is going off."


def test_a_provider_failure_falls_back_to_the_policy_verdict() -> None:
    def handler(request):
        return httpx.Response(500)

    d = Deliberator(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    surface, _detail, cost = d(event(), verdict("island"))

    assert surface == "island"
    assert cost == 0.0  # a failed thought is not billed


def test_unparseable_output_falls_back_without_crashing() -> None:
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "I think maybe?"}}]})

    d = Deliberator(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)))
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


def test_deliberation_cost_is_charged_to_the_budget(journal) -> None:
    journal.append("room", "alarm_started", "Alarm", trusted=True)

    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"worth_it": true, "say": "Alarm."}'}}]
        })

    d = Deliberator(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    mind = Mind(journal, deliberate=d, announcer=FakeAnnouncer())
    mind.tick(now=NOON)

    assert mind.why()[0]["provider"] == "llm"
    assert mind.why()[0]["cost"] > 0
