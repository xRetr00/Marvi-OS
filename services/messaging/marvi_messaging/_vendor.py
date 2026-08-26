"""Private compatibility bridge into the pinned messaging implementation.

Only this module knows the upstream package layout and legacy environment
names. Public Marvi APIs and Electron use MARVI_MESSAGING_* exclusively.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def vendor_root() -> Path:
    configured = os.environ.get("MARVI_MESSAGING_VENDOR_ROOT", "").strip()
    if configured:
        root = Path(configured).resolve()
    else:
        package_root = Path(__file__).resolve().parents[2]
        packaged = package_root.parent / "vendor"
        checkout = package_root.parents[1] / "vendor" / "marvi-agent"
        root = packaged if (packaged / "gateway" / "run.py").is_file() else checkout
    if not (root / "gateway" / "run.py").is_file():
        raise RuntimeError(f"Bundled messaging implementation is incomplete: {root}")
    return root


def activate(*, managed: bool) -> Path:
    """Activate the vendored library without exposing it as the app boundary."""
    root = vendor_root()
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    home = os.environ.get("MARVI_MESSAGING_HOME", "").strip()
    if not home:
        raise RuntimeError("MARVI_MESSAGING_HOME is required")

    # The pinned implementation still uses these internal compatibility names.
    # They are deliberately contained here and never form Electron's contract.
    os.environ["HERMES_HOME"] = home
    os.environ["MARVI_PARENT_PID"] = os.environ.get("MARVI_MESSAGING_PARENT_PID", "")
    if os.environ.get("MARVI_MESSAGING_EXTERNAL_SUPERVISOR") == "1":
        os.environ["HERMES_GATEWAY_EXTERNAL_SUPERVISOR"] = "1"
    if managed:
        os.environ["HERMES_MANAGED"] = "marvi-os"
    else:
        os.environ.pop("HERMES_MANAGED", None)

    os.environ["AI_AGENT"] = "marvi-os-messaging"
    os.environ["MARVI_MESSAGING_RUNTIME"] = "1"
    return root
