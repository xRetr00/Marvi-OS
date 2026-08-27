"""Activate Marvi's in-tree messaging engine."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def engine_root() -> Path:
    configured = os.environ.get("MARVI_MESSAGING_ENGINE_ROOT", "").strip()
    root = Path(configured).resolve() if configured else Path(__file__).resolve().parent / "engine"
    if not (root / "gateway" / "run.py").is_file():
        raise RuntimeError(f"Marvi messaging engine is incomplete: {root}")
    return root


def activate(*, managed: bool) -> Path:
    """Activate the Marvi-owned engine and its private profile contract."""
    root = engine_root()
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    home = os.environ.get("MARVI_MESSAGING_HOME", "").strip()
    if not home:
        raise RuntimeError("MARVI_MESSAGING_HOME is required")

    os.environ["MARVI_PARENT_PID"] = os.environ.get("MARVI_MESSAGING_PARENT_PID", "")
    if managed:
        os.environ["MARVI_MESSAGING_MANAGED"] = "marvi-os"
    else:
        os.environ.pop("MARVI_MESSAGING_MANAGED", None)

    os.environ["AI_AGENT"] = "marvi-os-messaging"
    os.environ["MARVI_MESSAGING_RUNTIME"] = "1"
    os.environ["MARVI_MESSAGING_DISABLE_LAZY_INSTALLS"] = "1"
    return root
