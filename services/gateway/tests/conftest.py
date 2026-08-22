"""Test isolation.

Marvi resolves its paths from `%LOCALAPPDATA%` by default, so anything that
constructs a store, configures logging, or builds the app writes into the real
installation. That was happening: a test run left `identity.log`, `mind.log`,
`providers.log`, `retry.log` and `voice.log` in the user's own log directory.

A test suite must never touch the machine it runs on. `MARVI_HOME` moves the
whole root, and every other path derives from it, so one fixture covers all of
them — including any added later, which is the point of having one root.
"""

from __future__ import annotations

import os
import tempfile

import pytest

# Set at import, before pytest collects anything.
#
# The fixture below covers each test, but logging configures itself once per
# process and that happens during collection — while a module is imported, and
# before any fixture has run. So the warnings captured at import time went to
# the real log directory, and three "logging started" lines appeared in the
# user's own errors.log from a test run.
#
# An environment variable set here is set before any of that.
_ISOLATED_HOME = tempfile.mkdtemp(prefix="marvi-tests-")
os.environ["MARVI_HOME"] = _ISOLATED_HOME
os.environ["MARVI_LOG_DIR"] = os.path.join(_ISOLATED_HOME, "logs")


@pytest.fixture(autouse=True)
def isolate_marvi_home(tmp_path_factory, monkeypatch):
    """Point every Marvi path at a temporary root, for every test."""
    home = tmp_path_factory.mktemp("marvi-home")
    monkeypatch.setenv("MARVI_HOME", str(home))
    monkeypatch.setenv("MARVI_LOG_DIR", str(home / "logs"))
    monkeypatch.setenv("MARVI_INSTALL_ROOT", str(home))
    # Individual overrides win over MARVI_HOME, so any left in the real
    # environment would defeat the isolation this fixture exists for.
    for leaked in (
        "MARVI_JOURNAL_DB",
        "MARVI_MEMORY_DB",
        "MARVI_CHAT_DB",
        "MARVI_IDENTITY_DIR",
        "MARVI_PROVIDER_CONFIG",
        "MARVI_TOKEN_STORE",
        "MARVI_AUDIT_LOG",
        "MARVI_VISION_DIR",
        "MARVI_SKILLS_DIR",
        "MARVI_MCP_CONFIG",
        "MARVI_USAGE_LEDGER",
    ):
        monkeypatch.delenv(leaked, raising=False)

    # And every provider credential.
    #
    # These are read from the environment, so a developer with a real key gets
    # a configured provider and CI does not -- the suite then passes locally
    # and fails on push, which is the worst way to find out. Sixteen tests did
    # exactly that. A test that needs a provider must say so and supply its
    # own, so the answer is the same on every machine.
    from marvi_gateway.providers import all_profiles

    for provider in all_profiles():
        for name in provider.key_env:
            monkeypatch.delenv(name, raising=False)
        if provider.base_url_env:
            monkeypatch.delenv(provider.base_url_env, raising=False)
        monkeypatch.delenv(provider.enabled_setting(), raising=False)
    monkeypatch.delenv("MARVI_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_ADMIN_KEY", raising=False)

    yield home

    # Logging is process-global: a listener left running from one test writes
    # the next test's records to a directory that has already been deleted.
    from marvi_gateway import logs

    logs.shutdown()


@pytest.fixture
def configured(monkeypatch):
    """Give a provider a credential for the length of one test.

    The counterpart to the credential-stripping above. Nothing is configured
    unless a test says it is, and a test that needs a provider gets a fake key
    rather than whichever real one happens to be in the environment -- so the
    answer is the same on a developer machine and on a runner with no keys at
    all.
    """

    def configure(name: str = "openai"):
        from marvi_gateway.providers import get

        profile = get(name)
        for variable in profile.key_env:
            monkeypatch.setenv(variable, "test-key")
        # Local providers need the switch as well as a URL: a reachable
        # endpoint is not a connection, and `configured()` says so.
        if profile.enabled_setting():
            monkeypatch.setenv(profile.enabled_setting(), "true")
        return profile

    return configure
