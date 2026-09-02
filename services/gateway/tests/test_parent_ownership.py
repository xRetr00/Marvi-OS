"""A child stands down when its launch is over, not when a PID vanishes.

Watching the parent PID alone is an inference, and PIDs are recycled: "my
parent is alive" was true of a parent that had exited hours earlier and whose
number now belonged to something unrelated. A Gateway outlived its desktop on
the strength of it, refused the Agent its provider credentials 285 times, and
answered every memory question with nothing.

See docs/PROCESS-OWNERSHIP.md.
"""

from __future__ import annotations

import json

import pytest

from marvi_gateway import parent


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    yield


def _record(tmp_path, launch: str) -> None:
    target = tmp_path / "state"
    target.mkdir(parents=True, exist_ok=True)
    (target / "runtime.json").write_text(json.dumps({"launchId": launch}), encoding="utf-8")


def test_no_record_is_not_a_different_launch(monkeypatch) -> None:
    """A Gateway started by hand has no record and must not exit at once."""
    monkeypatch.setenv(parent.LAUNCH_ENV, "")
    # No file at all reads as GONE, and a process with no launch id of its own
    # ignores the record entirely -- which is what keeps `uvicorn` in a
    # terminal from exiting the moment it starts.
    assert parent._launch_on_disk() == parent.GONE
    assert parent._superseded("") is False


def test_the_same_launch_keeps_running(tmp_path, monkeypatch) -> None:
    _record(tmp_path, "launch-one")
    monkeypatch.setenv(parent.LAUNCH_ENV, "launch-one")
    assert parent._superseded("launch-one") is False


def test_a_newer_launch_supersedes_this_one(tmp_path, monkeypatch) -> None:
    """The failure this exists for: relaunch, and the old child stands down.

    Without it the previous launch's Gateway keeps the port, keeps the old
    token, and the new Agent is refused its own credentials.
    """
    _record(tmp_path, "launch-two")
    monkeypatch.setenv(parent.LAUNCH_ENV, "launch-one")
    assert parent._superseded("launch-one") is True


def test_a_removed_record_means_shutdown(tmp_path, monkeypatch) -> None:
    """The desktop deletes the record before stopping its children.

    So an absent record, in a process that was started *with* a launch id, is
    the shutdown having begun -- and the child leaves without being killed.
    """
    _record(tmp_path, "launch-one")
    monkeypatch.setenv(parent.LAUNCH_ENV, "launch-one")
    assert parent._superseded("launch-one") is False
    (tmp_path / "state" / "runtime.json").unlink()
    assert parent._launch_on_disk() == parent.GONE
    assert parent._superseded("launch-one") is True


def test_a_half_written_record_is_not_a_shutdown(tmp_path, monkeypatch) -> None:
    """The race this nearly shipped with.

    The record is rewritten every time a child starts. A reader landing
    mid-write gets half a file, and the first version of this treated that
    exactly like "no record" -- so every child would have concluded the desktop
    had shut down, at the same moment, and exited together.
    """
    target = tmp_path / "state"
    target.mkdir(parents=True, exist_ok=True)
    (target / "runtime.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv(parent.LAUNCH_ENV, "launch-one")

    assert parent._launch_on_disk() == parent.UNREADABLE
    assert parent._superseded("launch-one") is False, "a torn read stood the stack down"


def test_a_record_without_a_launch_id_is_unreadable(tmp_path, monkeypatch) -> None:
    target = tmp_path / "state"
    target.mkdir(parents=True, exist_ok=True)
    (target / "runtime.json").write_text('{"bootId": "x"}', encoding="utf-8")
    monkeypatch.setenv(parent.LAUNCH_ENV, "launch-one")
    assert parent._launch_on_disk() == parent.UNREADABLE
    assert parent._superseded("launch-one") is False


def test_watch_returns_nothing_without_a_parent(monkeypatch) -> None:
    monkeypatch.delenv(parent.PARENT_ENV, raising=False)
    assert parent.watch() is None
