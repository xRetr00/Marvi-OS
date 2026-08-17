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

import pytest


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
    ):
        monkeypatch.delenv(leaked, raising=False)
    yield home

    # Logging is process-global: a listener left running from one test writes
    # the next test's records to a directory that has already been deleted.
    from marvi_gateway import logs

    logs.shutdown()
