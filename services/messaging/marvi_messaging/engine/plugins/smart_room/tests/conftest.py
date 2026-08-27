"""Keep smart-room tests out of the user's real Marvi profile."""

from __future__ import annotations

import pytest

from marvi_constants import reset_marvi_home_override, set_marvi_home_override


@pytest.fixture(autouse=True)
def isolated_marvi_home(tmp_path, monkeypatch):
    home = tmp_path / "marvi-home"
    monkeypatch.setenv("MARVI_MESSAGING_HOME", str(home))
    monkeypatch.setenv("MARVI_HOME", str(home))
    token = set_marvi_home_override(home)
    try:
        yield
    finally:
        reset_marvi_home_override(token)
