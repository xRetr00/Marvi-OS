"""The always-on wake word listener.

What is worth testing here is not the model -- that is trained, not written --
but the two decisions around it that were wrong in the previous design and are
easy to get wrong again: how the app is reached, and what the listener says
about itself while nobody is looking.
"""

from __future__ import annotations

import json
import os

from marvi_agent import wake_daemon


def test_wake_scoring_pauses_while_the_standalone_announcer_is_playing(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    marker = tmp_path / "state" / "announcing.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps({"pid": os.getpid(), "started_at": 100.0, "purpose": "proactive"}),
        encoding="utf-8",
    )

    assert wake_daemon.announcement_active(now=101.0) is True
    assert marker.is_file()


def test_the_windows_liveness_check_never_uses_os_kill(monkeypatch) -> None:
    monkeypatch.setattr(wake_daemon.os, "name", "nt")
    monkeypatch.setattr(
        wake_daemon.os,
        "kill",
        lambda *_args: (_ for _ in ()).throw(AssertionError("would terminate the Gateway")),
    )

    assert isinstance(wake_daemon._process_alive(os.getpid()), bool)


def test_a_stale_announcement_cannot_disable_wake_word(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    marker = tmp_path / "state" / "announcing.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps({"pid": os.getpid(), "started_at": 1.0}), encoding="utf-8"
    )

    assert wake_daemon.announcement_active(
        now=1.0 + wake_daemon.ANNOUNCEMENT_STALE_SECONDS + 1
    ) is False
    assert marker.exists() is False


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


# -- how the listener is started ----------------------------------------------


def test_the_registered_command_has_no_console(monkeypatch, tmp_path) -> None:
    """The Run key runs whatever it is given, and there is no "hidden" flag to
    pass it. A console program gets a console, so the listener sat behind a
    terminal window on the desktop for the whole session -- for a process whose
    entire job is to be invisible.

    `pythonw.exe` is the GUI-subsystem build and never creates one.
    """
    from pathlib import Path

    from marvi_agent import wake_autostart

    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    (scripts / "python.exe").write_text("", encoding="utf-8")
    (scripts / "pythonw.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(wake_autostart.sys, "executable", str(scripts / "python.exe"))
    monkeypatch.setattr(wake_autostart.sys, "platform", "win32")

    line = wake_autostart.command(Path("C:/x/services/agent"), Path("C:/x/Marvi.exe"))

    assert "pythonw.exe" in line
    assert "uv" not in line.lower(), "still going through uv, which opens a console"


def test_it_falls_back_to_uv_when_there_is_no_pythonw(monkeypatch, tmp_path) -> None:
    """A console is worse than the alternative; no wake word is worse still."""
    from pathlib import Path

    from marvi_agent import wake_autostart

    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    (scripts / "python.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(wake_autostart.sys, "executable", str(scripts / "python.exe"))
    monkeypatch.setattr(wake_autostart.sys, "platform", "win32")

    line = wake_autostart.command(Path("C:/x/services/agent"), Path("C:/x/Marvi.exe"))

    assert "wake_daemon" in line
    assert "run" in line


def test_the_chosen_microphone_is_in_the_command(monkeypatch, tmp_path) -> None:
    from pathlib import Path

    from marvi_agent import wake_autostart

    monkeypatch.setattr(wake_autostart, "interpreter", lambda: "C:/x/pythonw.exe")

    line = wake_autostart.command(
        Path("C:/x"), Path("C:/x/Marvi.exe"), 0.5, "Echo Cancelling Speakerphone (Konftel Ego)"
    )

    assert '--device "Echo Cancelling Speakerphone (Konftel Ego)"' in line


# -- turning it off, and not stacking it up -----------------------------------


def test_turning_it_off_stops_the_listener(monkeypatch) -> None:
    """Removing the registry value only decides what happens at the next login.

    On its own it left the process holding the microphone and still joining
    sessions when it heard its name, until a reboot. A switch that does not
    stop the thing it names is worse than no switch.
    """
    from marvi_agent import wake_autostart

    stopped: list[bool] = []
    monkeypatch.setattr(wake_autostart, "stop", lambda: stopped.append(True) or 1)

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(wake_autostart, "_key", lambda: Key())
    import winreg

    monkeypatch.setattr(winreg, "DeleteValue", lambda *_a: None)

    wake_autostart.disable()

    assert stopped, "the registry value went but the listener kept running"


def test_enabling_replaces_rather_than_accumulates(monkeypatch, tmp_path) -> None:
    """Two listeners competing for one microphone, both able to fire a join.

    It is also how a changed microphone takes effect now instead of at the next
    login: the device is baked into the command line, so the old process is
    still on the old one until it is stopped.
    """
    from pathlib import Path

    from marvi_agent import wake_autostart

    order: list[str] = []
    monkeypatch.setattr(wake_autostart, "stop", lambda: order.append("stop") or 0)
    monkeypatch.setattr(wake_autostart, "start_now", lambda _line: order.append("start"))
    monkeypatch.setattr(wake_autostart, "command", lambda *_a, **_k: "cmd")

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(wake_autostart, "_key", lambda: Key())
    import winreg

    monkeypatch.setattr(winreg, "SetValueEx", lambda *_a: None)

    wake_autostart.enable(Path("C:/x"), Path("C:/x/Marvi.exe"))

    assert order == ["stop", "start"]


# -- which microphones are offered --------------------------------------------


def test_one_microphone_is_offered_once(monkeypatch) -> None:
    """Windows lists each device once per host API, and MME truncates names to
    31 characters -- so the duplicates are not even equal. "Echo Cancelling
    Speakerphone (K" and "Echo Cancelling Speakerphone (Konftel Ego)" are one
    device, and the truncated one is the one nobody would recognise.
    """
    import sys
    from types import SimpleNamespace

    fake = SimpleNamespace(
        query_devices=lambda kind=None: (
            {"name": "Echo Cancelling Speakerphone (Konftel Ego)"}
            if kind == "input"
            else [
                {"name": "Echo Cancelling Speakerphone (K", "max_input_channels": 1},
                {"name": "Echo Cancelling Speakerphone (Konftel Ego)", "max_input_channels": 2},
                {"name": "Speakers (Realtek)", "max_input_channels": 0},
            ]
        ),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    from marvi_agent.wake_daemon import microphones

    found = microphones()

    assert [entry["name"] for entry in found] == ["Echo Cancelling Speakerphone (Konftel Ego)"]
    assert found[0]["default"] is True


def test_a_bluetooth_name_is_made_readable(monkeypatch) -> None:
    """They arrive with a newline and a driver path in the middle of the name,
    and the raw string is still what PortAudio has to be handed."""
    import sys
    from types import SimpleNamespace

    raw = "Headset (@System32" + chr(92) + "bth.sys,#2;%1 Hands-Free%0" + chr(13) + chr(10) + ";(AirPods))"
    fake = SimpleNamespace(
        query_devices=lambda kind=None: (
            {"name": ""} if kind == "input" else [{"name": raw, "max_input_channels": 1}]
        ),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    from marvi_agent.wake_daemon import microphones

    entry = microphones()[0]

    assert entry["name"] == raw
    assert "\n" not in str(entry["label"])
