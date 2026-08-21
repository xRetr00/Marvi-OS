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
