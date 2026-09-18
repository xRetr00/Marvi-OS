"""A snippet of Python with limits, run for real.

Every one of these runs a real interpreter under a real Job Object: the limits
are the feature, and a mocked limit proves nothing about whether the machine
survives a runaway loop.
"""

from __future__ import annotations

import os

import pytest

from marvi_gateway import sandbox
from marvi_gateway.tools import ToolRegistry

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Job Objects are Windows")


def test_it_runs_a_snippet_and_hands_back_what_it_printed() -> None:
    ran = sandbox.run("print(sum(range(10)))")

    assert ran["exit_code"] == 0
    assert ran["stdout"].strip() == "45"
    assert ran["timed_out"] is False


def test_a_snippet_that_asks_for_the_machine_is_stopped() -> None:
    """The limit that matters: this used to take the desktop with it."""
    ran = sandbox.run("a = bytearray(900 * 1024 * 1024)", memory=256 * 1024 * 1024)

    assert ran["exit_code"] != 0
    assert "MemoryError" in ran["stderr"]


def test_a_snippet_that_never_returns_is_killed() -> None:
    ran = sandbox.run("while True:\n    pass", timeout=2)

    assert ran["timed_out"] is True


def test_reaching_the_network_by_accident_says_what_to_use_instead() -> None:
    ran = sandbox.run("import socket\nsocket.socket()")

    assert "no network" in ran["stderr"]
    assert "web tools" in ran["stderr"]


def test_its_files_live_in_a_scratch_directory_and_do_not_survive(tmp_path) -> None:
    ran = sandbox.run("open('out.csv', 'w').write('a,b\\n1,2\\n')\nprint('written')")

    assert ran["files_made"] == ["out.csv"]
    assert ran["stdout"].strip() == "written"
    # Nothing is left on disk: the directory goes with the call.
    assert not any(tmp_path.iterdir())


def test_an_error_in_the_snippet_is_a_result_not_an_exception() -> None:
    ran = sandbox.run("1 / 0")

    assert ran["exit_code"] != 0
    assert "ZeroDivisionError" in ran["stderr"]


def test_the_limits_are_reported_including_what_they_are_not() -> None:
    ran = sandbox.run("print('hi')")

    assert ran["limits"]["seconds"] > 0
    # Said in the result, because a caller that believes this is a security
    # boundary will use it as one.
    assert "not a security boundary" in ran["limits"]["network"]


def test_the_tool_refuses_nothing_and_asks_nothing() -> None:
    registry = ToolRegistry()
    sandbox.register_sandbox_tools(registry)
    spec = registry.get("code_run")

    assert spec.sensitive is False
    assert registry.execute(spec, {"code": ""})["error"] == "there is no code to run"
    assert registry.execute(spec, {"code": "print(2 * 3)"})["stdout"].strip() == "6"
