"""The AppContainer: the half of the sandbox that is a boundary.

Whether the kernel actually refuses the handle is not something a test on an
arbitrary machine can settle -- a Python installed for every user cannot be
granted to the container at all, and there the sandbox honestly falls back. So
the real proof is written down as evidence in `docs/backlog/big.md`, taken on
the owner's host against a user-owned interpreter.

What is tested here is everything that got that proof wrong the first time.
Both of the bugs below produced the same symptom -- "it just doesn't start" --
with an error that pointed somewhere else entirely, so both are worth a test
that fails loudly rather than a comment.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from marvi_gateway import lowbox, sandbox


def test_the_environment_carries_the_variables_the_container_cannot_start_without() -> None:
    """`CreateProcessW` answers `ERROR_ENVVAR_NOT_FOUND` (203) for a container
    whose environment has no profile paths -- it redirects each of them into
    the container's own folder and has to read the original to do it.

    The first version passed `SYSTEMROOT`, `TEMP` and `TMP`, which is plenty
    for an ordinary process, and every launch failed with an error code that
    says nothing about profiles.
    """
    block = bytes(lowbox._environment(Path("C:/scratch"))).decode("utf-16-le")
    names = {entry.split("=", 1)[0].upper() for entry in block.split("\0") if "=" in entry}

    assert {"USERPROFILE", "APPDATA", "LOCALAPPDATA"} <= names
    assert {"SYSTEMROOT", "TEMP", "TMP"} <= names
    # Terminated by a second NUL, or Windows reads past the end of it.
    assert block.endswith("\0\0")


def test_the_environment_is_only_what_the_container_needs() -> None:
    """Not a copy of Marvi's own environment: the container cannot open any of
    these paths, but there is no reason to hand it API keys as well."""
    block = bytes(lowbox._environment(Path("C:/scratch"))).decode("utf-16-le")

    assert "API_KEY" not in block.upper()
    assert "C:\\scratch" in block  # its own scratch is where TEMP points


def test_an_existing_directory_is_granted_twice_and_the_second_pass_is_the_one_that_works(
    monkeypatch,
) -> None:
    """`(OI)(CI)` are container inheritance flags, and `icacls /T` drops an ACE
    carrying them when it reaches a file. The single command that looks like it
    grants a whole tree grants only the directory, every file under it keeps
    nothing, and the container then fails to start with `permission denied
    (os error 5)` -- from the loader, which does not mention permissions you
    can see anywhere in the code.
    """
    runs: list[list[str]] = []
    monkeypatch.setattr(lowbox, "_icacls", lambda arguments, why: runs.append(arguments) or True)

    lowbox._grant(Path("C:/python"), "S-1-15-2-x", "(RX)", existing=True)

    assert len(runs) == 2, "a directory with files in it needs both passes"
    assert "(OI)(CI)(RX)" in runs[0][2], "the inheritable ACE, for files that arrive later"
    assert "(RX)" in runs[1][2] and "(OI)" not in runs[1][2], "a plain ACE, for the files there now"
    assert "/T" in runs[1], "walked, because inheritance does not reach what already exists"


def test_a_fresh_directory_is_granted_once(monkeypatch) -> None:
    runs: list[list[str]] = []
    monkeypatch.setattr(lowbox, "_icacls", lambda arguments, why: runs.append(arguments) or True)

    lowbox._grant(Path("C:/scratch"), "S-1-15-2-x", "(F)")

    assert len(runs) == 1, "nothing is in it yet, so there is nothing to walk"


def test_the_launcher_talking_to_itself_is_not_the_snippet_speaking() -> None:
    """A `uv` virtual environment's `python.exe` is a trampoline that cannot
    read its own path inside the container. It says so, falls back, and works.
    On every successful run that line read like a failure."""
    said = lowbox._without_launcher_noise(
        "Failed to find real location of C:\\x\\python.exe\nTraceback (most recent call last):\n"
    )

    assert said == "Traceback (most recent call last):\n"
    # A snippet that prints those words itself still gets them back.
    assert lowbox._without_launcher_noise("  Failed to find real location of it\n") != ""


def test_the_setting_switches_it_off(monkeypatch) -> None:
    monkeypatch.setenv(lowbox.SETTING, "0")
    assert lowbox.wanted() is False
    monkeypatch.delenv(lowbox.SETTING)
    assert lowbox.wanted() is True, "a boundary is on unless the owner turns it off"


@pytest.mark.skipif(os.name != "nt", reason="AppContainers are Windows")
def test_the_result_always_says_which_isolation_ran(monkeypatch) -> None:
    """The rule the whole module exists to keep. A sandbox that quietly stops
    being a boundary is worse than one that never claimed to be."""
    monkeypatch.setenv(lowbox.SETTING, "0")
    sandbox.forget_isolation()
    try:
        ran = sandbox.run("print('hi')")
        assert ran["limits"]["isolation"] == "job"
        assert lowbox.SETTING in ran["limits"]["isolation_detail"]
        assert "not a security boundary" in ran["limits"]["network"]
    finally:
        sandbox.forget_isolation()
