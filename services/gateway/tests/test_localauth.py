"""The one door that hands out a credential.

`/providers/voice` answers with the provider's raw API key -- it has to, because
the Agent holds the credential and calls the provider itself, which is what
keeps the first spoken token off a second hop. It had nothing in front of it,
so anything that could reach loopback could read the key with one
unauthenticated GET.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from marvi_gateway import localauth


class Asking:
    """A request, as far as the guard is concerned."""

    def __init__(self, **headers: str) -> None:
        self.headers = {name.replace("_", "-"): value for name, value in headers.items()}


def test_a_browser_is_refused_even_without_a_token(monkeypatch) -> None:
    """`Sec-Fetch-Site` is a forbidden header name -- page script cannot set or
    remove it -- and no ordinary HTTP client sends it. Its presence means a
    browser engine is asking, and nothing that should be reading a credential
    is a browser. Enforced with or without a token, because it costs nothing
    and it is the drive-by shape."""
    monkeypatch.delenv(localauth.SETTING, raising=False)

    with pytest.raises(HTTPException) as refused:
        localauth.guard(Asking(sec_fetch_site="cross-site"))

    assert refused.value.status_code == 403


def test_a_page_this_gateway_served_is_not_a_drive_by(monkeypatch) -> None:
    """The one browser case that is not somebody else's tab."""
    monkeypatch.delenv(localauth.SETTING, raising=False)

    localauth.guard(Asking(sec_fetch_site="same-origin"))


def test_the_token_is_required_once_one_is_issued(monkeypatch) -> None:
    monkeypatch.setenv(localauth.SETTING, "a-real-token")

    with pytest.raises(HTTPException) as refused:
        localauth.guard(Asking())

    assert refused.value.status_code == 403


def test_the_agent_is_let_through(monkeypatch) -> None:
    """Both processes are started by the same supervisor with the same
    environment. That is what makes this the Agent and not a tab."""
    monkeypatch.setenv(localauth.SETTING, "a-real-token")

    localauth.guard(Asking(x_marvi_local="a-real-token"))


def test_a_wrong_token_is_refused(monkeypatch) -> None:
    monkeypatch.setenv(localauth.SETTING, "a-real-token")

    with pytest.raises(HTTPException):
        localauth.guard(Asking(x_marvi_local="not-the-token"))


def test_no_token_issued_means_no_token_required(monkeypatch) -> None:
    """A developer running the Gateway by hand, and the eval harness. A token
    nobody issued cannot be required without breaking every way of running this
    outside the app -- a deliberate limit, not an oversight: the guard is worth
    having in the shipped configuration and is not a claim to be airtight
    outside it."""
    monkeypatch.delenv(localauth.SETTING, raising=False)

    localauth.guard(Asking())


def test_a_token_left_on_disk_is_accepted_too(tmp_path, monkeypatch) -> None:
    """The failure this exists for: a Gateway the desktop adopted.

    Relaunch while an old Gateway still holds the port with a live parent and
    the new desktop adopts it. The adopted Gateway then checks a token from the
    previous launch while the new Agent presents the current one, and every
    request for the provider credential is refused. 285 of those in one day's
    log, and a voice job that died four seconds after the first.
    """
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    monkeypatch.setenv(localauth.SETTING, "a-token-from-the-previous-launch")
    written = tmp_path / localauth.TOKEN_FILE
    written.parent.mkdir(parents=True, exist_ok=True)
    written.write_text("the-token-this-launch-issued", encoding="utf-8")

    # Both are accepted: both were issued by a desktop that owns this install.
    localauth.guard(Asking(x_marvi_local="the-token-this-launch-issued"))
    localauth.guard(Asking(x_marvi_local="a-token-from-the-previous-launch"))
    with pytest.raises(HTTPException):
        localauth.guard(Asking(x_marvi_local="neither-of-them"))


def test_a_browser_is_still_refused_with_a_file_on_disk(tmp_path, monkeypatch) -> None:
    """The token is not the check that stops the drive-by, and never was."""
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    monkeypatch.delenv(localauth.SETTING, raising=False)
    written = tmp_path / localauth.TOKEN_FILE
    written.parent.mkdir(parents=True, exist_ok=True)
    written.write_text("a-real-token", encoding="utf-8")

    with pytest.raises(HTTPException):
        localauth.guard(Asking(sec_fetch_site="cross-site", x_marvi_local="a-real-token"))


def test_no_token_anywhere_leaves_the_guard_open(tmp_path, monkeypatch) -> None:
    """A developer running the Gateway by hand is not locked out of it."""
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    monkeypatch.delenv(localauth.SETTING, raising=False)
    assert localauth.expected() == []
    localauth.guard(Asking())
