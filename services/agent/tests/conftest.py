"""Test isolation for the Agent's suite.

The Gateway's tests have had this for a while; the Agent's had none, and it
showed. Running them wrote real warnings into the user's own `errors.log`:

    WARNING [gateway] marvi.wakeword — no wake word model at
    C:\\...\\Temp\\pytest-of-xRetro\\pytest-1226\\...\\absent.onnx

A line naming a pytest temporary directory, in the log a person reads to find
out what is wrong with their installation. The test was correct; it had simply
never been told where to put its output, so it used the machine's.

`MARVI_HOME` moves the whole root and every other path derives from it, which
is why one variable is enough. Set at import, before collection, because
logging configures itself once per process and does so while modules are being
imported — a fixture runs too late to catch that.
"""

from __future__ import annotations

import os
import tempfile

import pytest

_ISOLATED_HOME = tempfile.mkdtemp(prefix="marvi-agent-tests-")
os.environ["MARVI_HOME"] = _ISOLATED_HOME
os.environ["MARVI_LOG_DIR"] = os.path.join(_ISOLATED_HOME, "logs")


@pytest.fixture(autouse=True)
def isolate_marvi_home(tmp_path_factory, monkeypatch):
    """Point every Marvi path at a temporary root, for every test."""
    home = tmp_path_factory.mktemp("marvi-home")
    monkeypatch.setenv("MARVI_HOME", str(home))
    monkeypatch.setenv("MARVI_LOG_DIR", str(home / "logs"))
    yield home
