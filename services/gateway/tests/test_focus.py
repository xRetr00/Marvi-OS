"""Standing aside for a game, and saying so.

ActivityWatch has known the focused window since it was added and nothing ever
acted on it -- Marvi could tell you what was open and never did anything about
it. This is the difference between a machine that reports and one that notices.
"""

from __future__ import annotations

import pytest

from marvi_gateway import focus as focus_module
from marvi_gateway import voicing
from marvi_gateway.focus import Focus, is_heavy, pretty


@pytest.fixture
def playing(monkeypatch):
    """A fullscreen game with the card pegged, which is what a game looks like."""
    monkeypatch.setattr(focus_module, "fullscreen_now", lambda: True)
    monkeypatch.setattr(focus_module, "gpu_in_use", lambda: 96.0)


@pytest.fixture
def idle(monkeypatch):
    """The desktop: nothing fullscreen, card near idle."""
    monkeypatch.setattr(focus_module, "fullscreen_now", lambda: False)
    monkeypatch.setattr(focus_module, "gpu_in_use", lambda: 11.0)


class _Windows:
    """ActivityWatch, as far as `Focus` is concerned."""

    def __init__(self, *windows) -> None:
        self.windows = list(windows)

    def current_window(self):
        return self.windows.pop(0) if self.windows else None


def _w(app: str, title: str = ""):
    return {"app": app, "title": title, "at": "2026-09-06T07:00:00Z"}


def _settle(focus: Focus, times: int = 2):
    """`SETTLED_LOOKS` means nothing happens on the first sighting."""
    changes = []
    for _ in range(times):
        changes.extend(focus.look())
    return changes


def test_a_game_is_recognised(playing) -> None:
    assert is_heavy(_w("FC26.exe")) == "FC26"
    # And one nothing has ever heard of, which a name list could never do.
    assert is_heavy(_w("SomeIndieGame.exe")) == "SomeIndieGame"


def test_a_launcher_in_the_tray_is_not_a_game(idle) -> None:
    """The reported bug, and the reason the name list stopped deciding.

    Steam, Epic and Battle.net sit in the tray from login to shutdown using no
    GPU. Matching on the name meant Marvi stood down off the card permanently
    on a machine where nothing was being played, and the only symptom was that
    she never prewarmed again.
    """
    for window in (_w("EpicGamesLauncher.exe", "Epic Games"), _w("steam.exe", "Steam"),
                   _w("Battle.net.exe")):
        assert is_heavy(window) == "", f"{window['app']} was taken for a game"


def test_a_fullscreen_video_is_not_a_game(monkeypatch) -> None:
    # Fullscreen, but the card is barely working. Not a reason to go silent.
    monkeypatch.setattr(focus_module, "fullscreen_now", lambda: True)
    monkeypatch.setattr(focus_module, "gpu_in_use", lambda: 18.0)
    assert is_heavy(_w("chrome.exe", "YouTube")) == ""


def test_a_compile_is_not_a_game(monkeypatch) -> None:
    # The card is busy and nothing is fullscreen: she can still speak.
    monkeypatch.setattr(focus_module, "fullscreen_now", lambda: False)
    monkeypatch.setattr(focus_module, "gpu_in_use", lambda: 99.0)
    assert is_heavy(_w("Code.exe")) == ""


def test_without_gpu_telemetry_the_name_still_decides(monkeypatch) -> None:
    # No NVIDIA card to ask. Fullscreen plus a known name is what is left.
    monkeypatch.setattr(focus_module, "fullscreen_now", lambda: True)
    monkeypatch.setattr(focus_module, "gpu_in_use", lambda: None)
    assert is_heavy(_w("FC26.exe")) == "FC26"
    assert is_heavy(_w("Code.exe")) == "", "a fullscreen editor is not a game"


def test_ordinary_work_is_not_a_game(idle) -> None:
    for window in (_w("Code.exe", "session.py - Marvi-OS"), _w("chrome.exe", "Gmail"),
                   _w("WindowsTerminal.exe"), None):
        assert is_heavy(window) == "", f"{window} looked like a game"


def test_it_stands_down_and_says_so(playing) -> None:
    focus = Focus(_Windows(_w("FC26.exe"), _w("FC26.exe")))
    changes = _settle(focus)
    assert [c.kind for c in changes] == ["heavy_app_started"]
    assert focus.low_resource is True
    assert focus.because == "FC 26"


def test_alt_tabbing_does_not_flip_it(playing) -> None:
    """A glance at Discord mid-match is not the end of the session.

    Without the settling window this announces both ways every time somebody
    checks a message, which is worse than never having built it.
    """
    focus = Focus(_Windows(_w("FC26.exe"), _w("FC26.exe"), _w("Discord.exe"), _w("FC26.exe")))
    assert [c.kind for c in _settle(focus)] == ["heavy_app_started"]
    assert focus.look() == [], "reacted to a single glance away"
    assert focus.look() == []
    assert focus.low_resource is True, "gave up the mode over one alt-tab"


def test_it_comes_back_when_the_game_closes(monkeypatch) -> None:
    monkeypatch.setattr(focus_module, "fullscreen_now", lambda: True)
    monkeypatch.setattr(focus_module, "gpu_in_use", lambda: 96.0)
    focus = Focus(_Windows(*( [_w("FC26.exe")] * 2 + [_w("Code.exe")] * 2 )))
    _settle(focus)
    # The game exits: the desktop is back and the card goes quiet.
    monkeypatch.setattr(focus_module, "fullscreen_now", lambda: False)
    monkeypatch.setattr(focus_module, "gpu_in_use", lambda: 9.0)
    assert [c.kind for c in _settle(focus)] == ["heavy_app_ended"]
    assert focus.low_resource is False


def test_nothing_happens_without_activitywatch() -> None:
    assert Focus(None).look() == []
    assert Focus(None).low_resource is False


def test_she_says_something_a_person_would_say() -> None:
    event = {
        "source": "focus", "kind": "heavy_app_started", "trusted": True,
        "summary": "FC 26 started", "payload": {"app": "FC26", "name": "FC 26"}, "at": 0.0,
    }
    line = voicing.spoken(event, "Shereef")
    assert "FC 26" in line
    assert "heavy_app_started" not in line

    event["kind"] = "heavy_app_ended"
    assert "FC 26" in voicing.spoken(event, "Shereef")


def test_a_name_the_list_knows_is_said_properly() -> None:
    assert pretty("fc26") == "FC 26"
    assert pretty("Discord") == "Discord"
