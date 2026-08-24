"""The wake word, as the rest of the system sees it.

The listener runs in its own process, at login, outside everything the Gateway
supervises. So the only thing the Gateway can say about it is what it reads
from a file and a registry key -- and the reading has to distinguish a listener
that is running from one that was registered and then died, because those two
are indistinguishable from the outside and one of them is broken.
"""

from __future__ import annotations

import json
import time

# -- the standalone listener -------------------------------------------------


def test_a_listener_that_died_is_not_reported_as_running(tmp_path, monkeypatch) -> None:
    """The failure that used to be invisible.

    Registered but not running looks exactly like a wake word nobody has said
    the word to: Marvi never answers, and nothing anywhere explains it. A stale
    heartbeat is the only evidence, so it has to be read as one.
    """
    from marvi_gateway import wake

    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    state = tmp_path / "state"
    state.mkdir()
    (state / "wake.json").write_text(
        json.dumps({"running": True, "heartbeat": time.time() - 600})
    )

    assert wake.listener()["running"] is False


def test_a_beating_listener_is_reported_as_running(tmp_path, monkeypatch) -> None:
    from marvi_gateway import wake

    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    state = tmp_path / "state"
    state.mkdir()
    (state / "wake.json").write_text(json.dumps({"running": True, "heartbeat": time.time()}))

    assert wake.listener()["running"] is True


def test_no_listener_at_all_is_not_an_error(tmp_path, monkeypatch) -> None:
    """Nothing installed is a normal state, not a broken one."""
    from marvi_gateway import wake

    monkeypatch.setenv("MARVI_HOME", str(tmp_path))

    live = wake.listener()
    assert live["running"] is False
    assert live["error"] == ""


def test_a_detection_the_gateway_never_saw_still_counts(tmp_path, monkeypatch) -> None:
    """The listener fires while the Gateway may not even be running.

    That is the whole point of it, so its file is the more recent truth
    whenever it has one -- posting to `/voice/wake/heard` cannot be relied on.
    """
    from marvi_gateway import wake

    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    wake.forget()
    state = tmp_path / "state"
    state.mkdir()
    (state / "wake.json").write_text(
        json.dumps({"running": True, "heartbeat": time.time(), "heard_at": time.time()})
    )

    assert wake.status()["recently_heard"] is True


def test_the_run_key_name_matches_the_agent() -> None:
    """Two processes, two copies of the same registry name.

    The Gateway cannot import the Agent -- different environment -- so the name
    is duplicated. If they drift, the switch turns on a listener the status bar
    then reports as off.
    """
    from pathlib import Path

    from marvi_gateway import wake

    source = (
        Path(__file__).resolve().parents[2]
        / "agent"
        / "src"
        / "marvi_agent"
        / "wake_autostart.py"
    ).read_text(encoding="utf-8")

    assert f'VALUE_NAME = "{wake.VALUE_NAME}"' in source
    assert wake.RUN_KEY in source


def test_the_gateway_lists_microphones_without_the_agent(monkeypatch) -> None:
    """It asked the Agent by importing `marvi_agent.wake_daemon`, and in the
    running Gateway that raised "No module named 'marvi_agent'" twice a second
    for as long as the settings page was open, with an empty picker to show
    for it.

    They are separate uv projects. A cross-project import is only ever
    accidentally true.
    """
    import sys

    from marvi_gateway import wake

    monkeypatch.setitem(sys.modules, "marvi_agent", None)
    monkeypatch.setitem(sys.modules, "marvi_agent.wake_daemon", None)

    assert isinstance(wake.microphones(), list)


def test_one_microphone_is_offered_once(monkeypatch) -> None:
    """Windows lists each device once per host API and MME truncates names to
    31 characters, so the duplicates are not even equal."""
    import sys
    from types import SimpleNamespace

    from marvi_gateway import wake

    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(
            query_devices=lambda kind=None: (
                {"name": "Echo Cancelling Speakerphone (Konftel Ego)"}
                if kind == "input"
                else [
                    {"name": "Echo Cancelling Speakerphone (K", "max_input_channels": 1},
                    {"name": "Echo Cancelling Speakerphone (Konftel Ego)", "max_input_channels": 2},
                    {"name": "Speakers (Realtek)", "max_input_channels": 0},
                ]
            )
        ),
    )

    found = wake.microphones()

    assert [entry["name"] for entry in found] == ["Echo Cancelling Speakerphone (Konftel Ego)"]
    assert found[0]["default"] is True


def test_the_two_services_dedupe_microphones_the_same_way() -> None:
    """The Agent opens the device the Gateway offered. They enumerate
    separately because they are separate projects, so nothing but this keeps
    the two lists in step."""
    from pathlib import Path

    agent = (
        Path(__file__).resolve().parents[3]
        / "services"
        / "agent"
        / "src"
        / "marvi_agent"
        / "wake_daemon.py"
    ).read_text(encoding="utf-8")

    rule = "if not any(other != name and other.startswith(name) for other in names)"

    assert rule in agent, "the Agent no longer drops truncated duplicate names"
