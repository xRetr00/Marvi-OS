"""The island shows whose idea a line was.

`speaking` is Marvi's half of a conversation the user started. An announcement
is nobody's request, and the two used to render identically -- so the only way
to tell whether you had been asked something was to listen to the words.
"""

from __future__ import annotations

from marvi_gateway.announce import Announcer
from marvi_gateway.runtime import (
    ANNOUNCING,
    HOLD_ANNOUNCEMENT_SECONDS,
    AssistantPhase,
    RuntimeStore,
)


def test_announcing_is_a_phase_the_shell_knows() -> None:
    assert "announcing" in AssistantPhase.__args__
    assert ANNOUNCING["phase"] == "announcing"


said: list[str] = []


def _wired() -> tuple[Announcer, RuntimeStore, list[bool]]:
    store = RuntimeStore()
    said.clear()
    seen: list[bool] = []
    announcer = Announcer()

    def on_air(
        on: bool, text: str = "", source: str = "marvi", announcement_id: str = ""
    ) -> None:
        seen.append(on)
        said.append(text)
        if on:
            store.assistant = store.assistant.model_copy(update=ANNOUNCING)
        elif store.assistant.phase == "announcing":
            store.assistant = store.assistant.model_copy(update={"phase": "ready"})

    announcer.on_air = on_air
    return announcer, store, seen


def test_the_flag_goes_up_and_comes_back_down(monkeypatch) -> None:
    announcer, store, seen = _wired()
    monkeypatch.setattr(Announcer, "_play", lambda *_a, **_k: 1.0, raising=False)
    monkeypatch.setattr(Announcer, "_render", lambda *_a, **_k: b"", raising=False)

    announcer.speak("Your mailboxes are being deleted today.")

    assert seen and seen[0] is True, "never raised the flag"
    assert seen[-1] is False, "left the island claiming she is still talking"
    assert store.assistant.phase != "announcing"


def test_read_aloud_is_not_an_announcement(monkeypatch) -> None:
    """Read Aloud is something the user pressed. Captioning that "Marvi has
    something" would be a lie about who started it."""
    announcer, _store, seen = _wired()
    monkeypatch.setattr(Announcer, "_play", lambda *_a, **_k: 1.0, raising=False)
    monkeypatch.setattr(Announcer, "_render", lambda *_a, **_k: b"", raising=False)

    announcer.speak("Here is that article.", purpose="read_aloud")

    assert seen == [], "flagged a user-requested reading as unprompted"


def test_nothing_to_say_never_raises_the_flag() -> None:
    announcer, _store, seen = _wired()
    assert announcer.speak("   ")["played"] is False
    assert seen == []


def test_the_island_is_told_what_she_said(monkeypatch) -> None:
    """So it can show the words, not just that words happened.

    An announcement is over in four seconds and is the one thing on screen
    nobody asked for: you look up because you heard your name, and by then it
    has gone.
    """
    announcer, _store, _seen = _wired()
    monkeypatch.setattr(Announcer, "_play", lambda *_a, **_k: 1.0, raising=False)
    monkeypatch.setattr(Announcer, "_render", lambda *_a, **_k: b"", raising=False)

    announcer.speak("Hey Shereef, new email just came in from Icemail.")

    assert said[0].startswith("Hey Shereef"), f"the island was told {said[0]!r}"


def test_the_island_signal_has_one_stable_identity_and_source(monkeypatch) -> None:
    announcer = Announcer()
    signals: list[tuple[bool, str, str]] = []
    announcer.on_air = lambda on, _text, source, item_id: signals.append((on, source, item_id))
    monkeypatch.setattr(Announcer, "_play", lambda *_a, **_k: 1.0, raising=False)
    monkeypatch.setattr(Announcer, "_render", lambda *_a, **_k: b"", raising=False)

    announcer.speak("The reminder is due.", source="schedule:reminder")

    assert signals[0][0] is True and signals[-1][0] is False
    assert signals[0][1] == "schedule:reminder"
    assert signals[0][2] == signals[-1][2]


def test_it_is_held_long_enough_to_read() -> None:
    # Long enough to read twice, short enough that it is not still there when
    # you next glance at the machine.
    assert 25.0 <= HOLD_ANNOUNCEMENT_SECONDS <= 60.0
