"""The always-on wake word listener.

What is worth testing here is not the model -- that is trained, not written --
but the two decisions around it that were wrong in the previous design and are
easy to get wrong again: how the app is reached, and what the listener says
about itself while nobody is looking.
"""

from __future__ import annotations

import json

from marvi_agent import wake_daemon


def test_the_app_is_reached_with_one_command_either_way(monkeypatch) -> None:
    """Running or closed, it is the same call.

    The listener must not ask whether Marvi is open. It would have to answer
    racily, and wrongly during the seconds she is starting; Electron's
    single-instance lock answers it correctly for free.
    """
    monkeypatch.delenv("MARVI_APP_COMMAND", raising=False)

    assert wake_daemon.app_command(r"C:\Marvi\Marvi.exe") == [r"C:\Marvi\Marvi.exe", "--wake"]


def test_the_app_path_is_given_not_guessed(monkeypatch) -> None:
    """Guessing from this process found a virtual environment, not the app."""
    monkeypatch.setenv("MARVI_INSTALL_ROOT", r"D:\Marvi")
    monkeypatch.delenv("MARVI_APP_COMMAND", raising=False)

    assert wake_daemon.app_command()[0].endswith("Marvi.exe")


def test_state_says_it_is_alive(tmp_path, monkeypatch) -> None:
    """The heartbeat is the whole reason the file exists.

    Without it the UI cannot tell a listener that is running from one that
    crashed at login, and those look identical from the outside: Marvi simply
    never answers to her name.
    """
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))

    wake_daemon.write_state(running=True, heartbeat=123.0)

    written = json.loads((tmp_path / "state" / "wake.json").read_text())
    assert written["running"] is True
    assert written["heartbeat"] == 123.0
    assert written["pid"] > 0


def test_writing_state_never_raises(tmp_path, monkeypatch) -> None:
    """A listener that works must not stop because its status file cannot be
    written. The file is a courtesy to the UI, not part of hearing her name."""
    # A file where the directory has to go, so both the mkdir and the write
    # fail -- the shape a real read-only or occupied path takes.
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    monkeypatch.setenv("MARVI_HOME", str(blocked))

    wake_daemon.write_state(running=True)  # must not raise


def test_a_missing_model_is_reported_rather_than_crashed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    monkeypatch.setenv("MARVI_WAKE_MODEL", str(tmp_path / "absent.onnx"))

    assert wake_daemon.listen(0.5) == 1

    written = json.loads((tmp_path / "state" / "wake.json").read_text())
    assert written["running"] is False
    assert "absent.onnx" in written["error"]


def test_the_window_is_long_enough_for_the_model_to_have_an_opinion() -> None:
    """Handed less than about two seconds, `predict` returns exactly 0.0.

    Not "no wake word" -- "I was not given enough audio". The two read
    identically, which is how an earlier version looked like a model that never
    fired when it was really a buffer that was never full.
    """
    assert wake_daemon.WINDOW_SECONDS >= 2.0
    # The word must not be able to straddle a boundary and be missed by both
    # halves, so the hop is at most half the window.
    assert wake_daemon.HOP_SECONDS <= wake_daemon.WINDOW_SECONDS / 2
