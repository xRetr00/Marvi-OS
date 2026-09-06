"""The island shows whose idea a line was.

`speaking` is Marvi's half of a conversation the user started. An announcement
is nobody's request, and the two used to render identically -- so the only way
to tell whether you had been asked something was to listen to the words.
"""

from __future__ import annotations

from marvi_gateway.announce import Announcer
from marvi_gateway.runtime import ANNOUNCING, AssistantPhase, RuntimeStore


def test_announcing_is_a_phase_the_shell_knows() -> None:
    assert "announcing" in AssistantPhase.__args__
    assert ANNOUNCING["phase"] == "announcing"


def _wired() -> tuple[Announcer, RuntimeStore, list[bool]]:
    store = RuntimeStore()
    seen: list[bool] = []
    announcer = Announcer()

    def on_air(on: bool) -> None:
        seen.append(on)
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
