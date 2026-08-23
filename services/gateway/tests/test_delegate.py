"""Handing a coding job to a coding agent.

The interesting properties are not "does it run a subprocess". They are:
does it refuse when there is nowhere it is allowed to work, is the read-only
mode the one you get by omission, and can the task text become a command.
"""

from __future__ import annotations

import time

import pytest

from marvi_gateway import delegate


@pytest.fixture(autouse=True)
def clean_jobs():
    delegate._jobs.clear()
    yield
    delegate._jobs.clear()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVI_WORKSPACE_ROOT", str(tmp_path))
    return tmp_path


def test_it_refuses_when_there_is_nowhere_it_may_work(monkeypatch) -> None:
    """A coding agent pointed at an unconfigured root is the worst possible
    place to start guessing, so absent configuration refuses rather than
    defaulting to the whole disk."""
    monkeypatch.delenv("MARVI_WORKSPACE_ROOT", raising=False)

    answer = delegate.start("look at the thing")

    assert answer["ok"] is False
    assert "MARVI_WORKSPACE_ROOT" in answer["detail"]


def test_read_only_is_what_you_get_by_omission(workspace, monkeypatch) -> None:
    """"Change my source code" must not be arrived at by leaving an argument
    out. This asserts the argv, because the mode is enforced by the CLI that
    receives it and nothing here would notice if it were dropped."""
    seen: dict[str, list[str]] = {}

    monkeypatch.setattr(delegate.shutil, "which", lambda _cmd: "claude")
    monkeypatch.setattr(
        delegate.threading, "Thread", lambda target, args, daemon: _Recorder(seen, args)
    )

    delegate.start("why is the room offline")

    assert seen["argv"][1:4] == ["-p", "--permission-mode", "plan"]

    delegate.start("fix the room", mode="fix")

    assert seen["argv"][1:4] == ["-p", "--permission-mode", "acceptEdits"]


def test_codex_gets_its_own_sandbox_flags(workspace, monkeypatch) -> None:
    seen: dict[str, list[str]] = {}
    monkeypatch.setattr(delegate.shutil, "which", lambda _cmd: "codex")
    monkeypatch.setattr(
        delegate.threading, "Thread", lambda target, args, daemon: _Recorder(seen, args)
    )

    delegate.start("look", coder="codex")

    assert seen["argv"][1:4] == ["exec", "--sandbox", "read-only"]


def test_the_task_is_an_argument_and_never_a_command(workspace, monkeypatch) -> None:
    """The task is text the model wrote from what a user said. It is passed as
    one element of an argv list, so a semicolon in it is a semicolon."""
    seen: dict[str, list[str]] = {}
    monkeypatch.setattr(delegate.shutil, "which", lambda _cmd: "claude")
    monkeypatch.setattr(
        delegate.threading, "Thread", lambda target, args, daemon: _Recorder(seen, args)
    )

    delegate.start("fix it; rm -rf / && echo pwned")

    assert seen["argv"][-1] == "fix it; rm -rf / && echo pwned"
    assert len(seen["argv"]) == 5


def test_an_unknown_mode_is_refused_rather_than_treated_as_fix(workspace) -> None:
    answer = delegate.start("do it", mode="yolo")

    assert answer["ok"] is False
    assert "investigate or fix" in answer["detail"]


def test_starting_does_not_wait_for_the_agent(workspace, monkeypatch) -> None:
    """The whole point: a spoken conversation carries on while it runs."""
    monkeypatch.setattr(delegate.shutil, "which", lambda _cmd: "claude")

    def slow(argv, **_kwargs):
        time.sleep(5)
        raise AssertionError("should never be awaited")

    monkeypatch.setattr(delegate.subprocess, "run", slow)

    began = time.monotonic()
    answer = delegate.start("something long")
    elapsed = time.monotonic() - began

    assert answer["ok"] is True
    assert answer["state"] == "running"
    assert elapsed < 1.0, f"start() blocked for {elapsed:.1f}s"


def test_a_finished_job_reports_what_came_back(workspace, monkeypatch) -> None:
    monkeypatch.setattr(delegate.shutil, "which", lambda _cmd: "claude")

    class Finished:
        stdout = "the plugin was updated after the Gateway started"
        stderr = ""
        returncode = 0

    monkeypatch.setattr(delegate.subprocess, "run", lambda *a, **k: Finished())

    job = delegate.start("why")["id"]
    for _ in range(50):
        answer = delegate.status(job)
        if answer["state"] != "running":
            break
        time.sleep(0.05)

    assert answer["state"] == "done"
    assert "updated after the Gateway started" in answer["output"]


def test_a_failing_agent_is_not_reported_as_done(workspace, monkeypatch) -> None:
    monkeypatch.setattr(delegate.shutil, "which", lambda _cmd: "claude")

    class Failed:
        stdout = ""
        stderr = "could not authenticate"
        returncode = 1

    monkeypatch.setattr(delegate.subprocess, "run", lambda *a, **k: Failed())

    job = delegate.start("why")["id"]
    for _ in range(50):
        answer = delegate.status(job)
        if answer["state"] != "running":
            break
        time.sleep(0.05)

    assert answer["state"] == "failed"
    assert answer["exit_code"] == 1


def test_only_so_many_at_once(workspace, monkeypatch) -> None:
    monkeypatch.setattr(delegate.shutil, "which", lambda _cmd: "claude")
    monkeypatch.setattr(
        delegate.threading, "Thread", lambda target, args, daemon: _Recorder({}, args)
    )

    for _ in range(delegate.MAX_RUNNING):
        assert delegate.start("work")["ok"] is True

    answer = delegate.start("one more")

    assert answer["ok"] is False
    assert "already running" in answer["detail"]


def test_delegating_asks_first() -> None:
    """It runs an agent that can edit the user's source code, so it is theirs
    to allow. Checking the registration rather than the flow, because the
    confirmation machinery is the router's and is tested there."""

    class Registry:
        def __init__(self):
            self.specs = {}

        def register(self, spec):
            self.specs[spec.name] = spec

    registry = Registry()
    delegate.register_delegate_tools(registry)

    assert registry.specs["delegate_to_coder"].sensitive is True
    # Reading a job's state changes nothing, and asking to check on something
    # is the moment a confirmation is most irritating.
    assert registry.specs["delegated_status"].sensitive is False


class _Recorder:
    """Stands in for the worker thread, capturing the argv it was handed."""

    def __init__(self, into: dict, args: tuple) -> None:
        into["argv"] = args[1]

    def start(self) -> None:
        return None
