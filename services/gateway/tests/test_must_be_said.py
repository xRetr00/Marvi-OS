"""The handful of things a model is not allowed to talk her out of.

Deliberation exists to stop Marvi narrating every light change and it is right
about almost everything. It was not right about this, from the owner's own
decision log:

    23:11:34  Welcome. Shereef isn't here right now.  silent
              not worth interrupting                  openrouter 1583ms

A welcome that is not said is not a quiet welcome. It is a missing one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from marvi_gateway.mind import Mind
from marvi_gateway.policy import MUST_BE_SAID, must_be_said


def _journal(event):
    class _J:
        def pending(self, limit=20):
            return [dict(event, id=1)]

        def tokens_since(self, _when):
            return 0

        def last_surfaced(self, _s, _k):
            return None

        def seen_recently(self, *_a, **_k):
            # Deliberately high: repetition is what damps an event, and a
            # welcome is repetitive by nature.
            return 9

        def record_decision(self, *_a, **_k):
            return 1

        def mark_processed(self, *_a, **_k):
            return None

    return _J()


WELCOME = {
    "source": "room", "kind": "room_welcome", "trusted": True,
    "summary": "Welcome. Shereef isn't here right now.",
    "payload": {}, "at": 0.0,
}


def test_a_model_may_not_silence_a_welcome() -> None:
    said: list[str] = []

    def deliberate(_event, _verdict):
        return "silent", "not worth interrupting", 120

    mind = Mind(_journal(WELCOME))
    mind.deliberate = deliberate
    mind.announcer = type("A", (), {"speak": lambda _s, text: said.append(text) or {"played": True}})()

    mind.tick(now=datetime(2026, 9, 7, 12, 0, tzinfo=UTC))

    assert said, "the model talked her out of the welcome"


def test_a_model_may_still_reword_it() -> None:
    """Quieter is refused; different words are not. The model's job here is
    phrasing and the marginal calls, not vetoing the decision itself."""
    said: list[str] = []

    def deliberate(_event, verdict):
        return verdict.surface, "Hey, welcome back.", 120

    mind = Mind(_journal(WELCOME))
    mind.deliberate = deliberate
    mind.announcer = type("A", (), {"speak": lambda _s, text: said.append(text) or {"played": True}})()

    mind.tick(now=datetime(2026, 9, 7, 12, 0, tzinfo=UTC))
    assert said == ["Hey, welcome back."]


def test_an_ordinary_event_can_still_be_silenced() -> None:
    # The gate is narrow on purpose: everything else keeps its veto.
    said: list[str] = []
    light = {**WELCOME, "kind": "light_changed", "summary": "light 80%"}

    mind = Mind(_journal(light))
    mind.deliberate = lambda _e, _v: ("silent", "not worth interrupting", 90)
    mind.announcer = type("A", (), {"speak": lambda _s, text: said.append(text) or {"played": True}})()

    mind.tick(now=datetime(2026, 9, 7, 12, 0, tzinfo=UTC))
    assert said == []


@pytest.mark.parametrize("kind", sorted(MUST_BE_SAID))
def test_every_entry_is_a_source_and_kind_pair(kind) -> None:
    source, _, name = kind.partition(":")
    assert source and name, f"{kind!r} is not source:kind"
    assert must_be_said({"source": source, "kind": name})


def test_the_veto_text_is_never_spoken() -> None:
    """What reached the room, from the owner's own decision log:

        00:19:01  FC 26 started  speak  "not worth interrupting"

    `proposed_detail` is the model's reason for wanting silence, not a line to
    deliver. Overriding the verdict and keeping its words made Marvi read the
    veto out loud.
    """
    said: list[str] = []
    game = {
        "source": "focus", "kind": "heavy_app_started", "trusted": True,
        "summary": "FC 26 started",
        "payload": {"app": "FC26", "name": "FC 26"}, "at": 0.0,
    }

    mind = Mind(_journal(game))
    mind.deliberate = lambda _e, _v: ("silent", "not worth interrupting", 200)
    mind.announcer = type("A", (), {"speak": lambda _s, t: said.append(t) or {"played": True}})()

    mind.tick(now=datetime(2026, 9, 7, 12, 0, tzinfo=UTC))

    assert said, "the game-mode line was silenced"
    assert "not worth interrupting" not in said[0], f"read the veto aloud: {said[0]!r}"
    assert "FC 26" in said[0], f"lost the template line: {said[0]!r}"
