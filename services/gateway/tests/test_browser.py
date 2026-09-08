"""The browser switch, and the guard that used to live beside it.

This file used to test `BrowserSession` — the pre-Phase-14 browser, one
long-lived Playwright page with eight tools of its own. That browser was
replaced by `browser_workspace` and never removed, so two vocabularies for the
same job sat in the tree: `browser_read` in the dead one, `browser_action(read)`
in the live one. The model reached for the shape it half-recognised and called
`browser_control command=read`, which is a command on neither, and burned the
turn's tool budget finding that out.

The dead module is gone. What is checked here is what survived it: the switch,
and — retargeted at the live browser — the refusal that mattered most.
"""

from __future__ import annotations

import pytest

from marvi_gateway.browser import browser_enabled
from marvi_gateway.web import WebRefusedError


def test_the_browser_is_off_unless_asked_for(monkeypatch) -> None:
    """A browser is a real resource cost; it does not start on a hunch."""
    monkeypatch.delenv("MARVI_BROWSER", raising=False)
    assert browser_enabled() is False

    for value in ("1", "true", "on", "yes", "TRUE"):
        monkeypatch.setenv("MARVI_BROWSER", value)
        assert browser_enabled() is True, value

    for value in ("0", "off", "", "no", "maybe"):
        monkeypatch.setenv("MARVI_BROWSER", value)
        assert browser_enabled() is False, value


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:17842/state",
        "http://localhost:8765",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
    ],
)
def test_the_browser_cannot_be_pointed_at_private_or_local_targets(url) -> None:
    """The one guarantee worth carrying across from the old browser.

    Loopback is where the Gateway itself listens and 169.254.169.254 is the
    cloud metadata endpoint; a browsing agent that can be talked into either
    is a credential leak with a user interface. `browser_workspace._url`
    enforces it before navigating, and a route handler enforces it again on
    every request including redirect destinations.
    """
    from marvi_gateway.browser_workspace import BrowserWorkspace

    workspace = BrowserWorkspace.__new__(BrowserWorkspace)
    workspace.allowed_origins = ()

    with pytest.raises(WebRefusedError):
        workspace._url(url)


def test_an_allowed_origin_is_still_allowed() -> None:
    """The escape hatch exists so a local service can be browsed on purpose."""
    from marvi_gateway.browser_workspace import BrowserWorkspace

    workspace = BrowserWorkspace.__new__(BrowserWorkspace)
    workspace.allowed_origins = ("http://localhost:8765",)

    workspace._url("http://localhost:8765/anything")


def test_url_credentials_are_refused() -> None:
    """`https://user:pass@host` puts a secret in every log line that URL
    touches, and the page can read it back out of `location`."""
    from marvi_gateway.browser_workspace import BrowserWorkspace

    workspace = BrowserWorkspace.__new__(BrowserWorkspace)
    workspace.allowed_origins = ()

    with pytest.raises(ValueError, match="credentials"):
        workspace._url("https://someone:secret@example.com/")
