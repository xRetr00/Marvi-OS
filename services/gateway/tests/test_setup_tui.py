"""The setup screen.

Two things matter and neither is how it looks. A scripted `marvi setup` must
still be the command it was -- anything else breaks installers and CI silently,
and a setup tool that hangs a build waiting for a keypress is worse than one
that is ugly. And the screen has to show what is *not* configured, because that
is the question it exists to answer: the CLI would happily tell you it had
installed everything while web search sat there doing nothing for want of a
backend.
"""

from __future__ import annotations

import argparse

import pytest

from marvi_gateway import cli
from marvi_gateway.setup import tui


def args(**kwargs) -> argparse.Namespace:
    base = {"what": [], "yes": False, "essential": False, "dry_run": False}
    return argparse.Namespace(**{**base, **kwargs})


@pytest.mark.parametrize(
    "given",
    [
        args(what=["voice"]),
        args(yes=True),
        args(essential=True),
        args(dry_run=True),
    ],
)
def test_any_flag_or_argument_keeps_the_old_command(given, monkeypatch) -> None:
    """The installer runs `--essential`; CI runs `--yes`. Neither may block."""
    monkeypatch.setattr(tui, "available", lambda: True)

    assert cli._wants_tui(given) is False


def test_a_bare_interactive_setup_opens_the_screen(monkeypatch) -> None:
    monkeypatch.setattr(tui, "available", lambda: True)

    assert cli._wants_tui(args()) is True


def test_a_pipe_gets_the_cli(monkeypatch) -> None:
    """Redirected output means nobody is there to answer a prompt."""
    monkeypatch.setattr(tui, "available", lambda: False)

    assert cli._wants_tui(args()) is False


# -- what the screen says ----------------------------------------------------


def test_a_capability_with_nothing_set_is_not_ready(monkeypatch) -> None:
    web = next(c for c in tui.CAPABILITIES if c.key == "web")
    for setting in web.settings:
        monkeypatch.delenv(setting.name, raising=False)

    assert tui._ready(web) is False


def test_web_search_needs_one_backend_not_every_backend(monkeypatch) -> None:
    """It is a choice between SearXNG and Brave, not a list to complete."""
    web = next(c for c in tui.CAPABILITIES if c.key == "web")
    for setting in web.settings:
        monkeypatch.delenv(setting.name, raising=False)
    monkeypatch.setenv("SEARXNG_URL", "http://localhost:8080")

    assert tui._ready(web) is True


def test_a_key_is_never_shown_in_the_clear(monkeypatch) -> None:
    """This screen gets read over a shoulder and pasted into bug reports."""
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "BSA-super-secret-value")
    setting = next(
        s
        for c in tui.CAPABILITIES
        for s in c.settings
        if s.name == "BRAVE_SEARCH_API_KEY"
    )

    shown = tui._shown(setting)

    assert "super-secret-value" not in shown
    assert shown != "[dim]not set[/dim]"


def test_a_switch_reads_as_on_or_off(monkeypatch) -> None:
    setting = next(
        s for c in tui.CAPABILITIES for s in c.settings if s.name == "MARVI_BROWSER"
    )

    monkeypatch.setenv("MARVI_BROWSER", "true")
    assert "on" in tui._shown(setting)

    monkeypatch.setenv("MARVI_BROWSER", "0")
    assert "off" in tui._shown(setting)


def test_every_capability_names_settings_that_the_code_reads() -> None:
    """A screen offering a setting nothing reads is worse than no screen.

    Each of these is checked against the module that gates the capability, so
    renaming the flag without renaming it here fails rather than quietly
    offering a switch that does nothing.
    """
    from pathlib import Path

    # Both services, because the screen configures both. The spoken language is
    # read by the Agent, not the Gateway, and scanning only one package made
    # this fail for a setting that is entirely real.
    gateway = Path(tui.__file__).resolve().parents[1]
    services = gateway.parents[2]
    everything = " ".join(
        path.read_text(encoding="utf-8", errors="replace")
        for root in (gateway, services / "agent" / "src")
        for path in root.rglob("*.py")
        if path.name != "tui.py"
    )
    for capability in tui.CAPABILITIES:
        for setting in capability.settings:
            assert setting.name in everything, f"{setting.name} is read by nothing"


# -- the two ways a status screen lies ---------------------------------------


def browser() -> tui.Setting:
    return next(s for c in tui.CAPABILITIES for s in c.settings if s.name == "MARVI_BROWSER")


def test_a_switch_turned_off_is_not_configured(monkeypatch) -> None:
    """It showed ready because the variable was set -- to "0"."""
    monkeypatch.setenv("MARVI_BROWSER", "0")
    capability = next(c for c in tui.CAPABILITIES if c.key == "browser")

    assert tui._ready(capability) is False


def test_a_default_that_is_on_reads_as_configured(monkeypatch) -> None:
    """Announcements are on unless turned off. "not set" read as a gap."""
    monkeypatch.delenv("MARVI_ANNOUNCE", raising=False)
    capability = next(c for c in tui.CAPABILITIES if c.key == "announce")

    assert tui._ready(capability) is True
    setting = capability.settings[0]
    assert "on" in tui._shown(setting)
    assert "default" in tui._shown(setting)


def test_an_unset_setting_with_no_default_says_so(monkeypatch) -> None:
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    setting = next(
        s for c in tui.CAPABILITIES for s in c.settings if s.name == "BRAVE_SEARCH_API_KEY"
    )

    assert tui._shown(setting) == "[dim]not set[/dim]"


def test_the_screen_prints_on_a_terminal_that_cannot_do_unicode() -> None:
    """Marvi is a Windows product and a legacy console is cp1252.

    Rich owns the box drawing and substitutes for legacy consoles itself; what
    this pins is that nothing *we* write needs more than ASCII.
    """
    from pathlib import Path

    source = Path(tui.__file__).read_text(encoding="utf-8")
    body = source.split('"""', 2)[2]  # the module docstring is never printed
    offenders = sorted({ch for ch in body if ord(ch) > 127})

    assert not offenders, f"cannot be printed on a legacy console: {offenders}"
