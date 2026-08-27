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
        Path(__file__).resolve().parents[3] / "apps" / "wake-host" / "src" / "autostart.rs"
    ).read_text(encoding="utf-8")

    assert f'pub const VALUE: &str = "{wake.VALUE_NAME}";' in source
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


def test_the_picker_offers_what_the_listener_can_open(monkeypatch, tmp_path) -> None:
    """Two lists, and they were not the same list.

    PortAudio here offered ten devices -- every host API's view of the machine,
    plus "Microsoft Sound Mapper - Input", which is not a microphone -- where
    the listener's cpal could open three. Choosing one of the other seven wrote
    a name the listener matched nothing against, so it fell back to the default
    microphone while Settings showed the device you picked.

    Deduping the two enumerations was the old answer and it could not work:
    they see different devices, not differently spelled ones.
    """
    import json

    from marvi_gateway import wake

    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "wake.json").write_text(
        json.dumps(
            {
                "pid": 1,
                "running": True,
                "heartbeat": time.time(),
                "devices": ["Echo Cancelling Speakerphone (Konftel Ego)", "Microphone (Realtek)"],
                "default_device": "Microphone (Realtek)",
            }
        ),
        encoding="utf-8",
    )

    offered = wake.microphones()

    assert [row["name"] for row in offered] == [
        "Echo Cancelling Speakerphone (Konftel Ego)",
        "Microphone (Realtek)",
    ]
    # Named by the listener rather than taken from the order. Enumeration order
    # is not preference order: taking the first put a game controller at the
    # top of the picker labelled "currently the system default".
    assert [row["default"] for row in offered] == [False, True]


def test_the_picker_still_answers_before_the_listener_has_ever_run(monkeypatch, tmp_path) -> None:
    """An empty picker is a worse settings page than an imperfect one."""
    from marvi_gateway import wake

    monkeypatch.setenv("MARVI_HOME", str(tmp_path))

    assert isinstance(wake.microphones(), list)


def test_a_listener_that_died_is_not_a_listener_starting_up(monkeypatch, tmp_path) -> None:
    """The status bar said STARTING for thirty hours.

    "Registered but not running" was reported as one state and it is two: a
    listener registered a second ago has not started yet, and one whose last
    heartbeat was yesterday morning is dead. Told apart, the first is worth
    waiting for and the second is worth a button.
    """
    import json
    import time

    from marvi_gateway import wake

    state = tmp_path / "wake.json"
    state.write_text(
        json.dumps({"pid": 34608, "running": True, "heartbeat": time.time() - 107_000}),
        encoding="utf-8",
    )
    monkeypatch.setattr(wake, "listener_state_path", lambda: state)

    live = wake.listener()

    assert live["running"] is False
    assert live["ever_ran"] is True
    assert live["silent_for"] > 100_000


def test_a_listener_that_has_never_run_says_so(monkeypatch, tmp_path) -> None:
    """No state file at all: it was registered and has not started yet, which
    is the one case where waiting is the right advice."""
    from marvi_gateway import wake

    monkeypatch.setattr(wake, "listener_state_path", lambda: tmp_path / "absent.json")

    live = wake.listener()

    assert live["running"] is False
    assert live["ever_ran"] is False
    assert live["silent_for"] is None


def test_a_beating_listener_is_running(monkeypatch, tmp_path) -> None:
    import json
    import time

    from marvi_gateway import wake

    state = tmp_path / "wake.json"
    state.write_text(
        json.dumps({"running": True, "heartbeat": time.time()}), encoding="utf-8"
    )
    monkeypatch.setattr(wake, "listener_state_path", lambda: state)

    assert wake.listener()["running"] is True
