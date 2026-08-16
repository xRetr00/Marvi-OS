"""Where provider settings actually live.

The registry reads `os.environ` and nothing else, which is what keeps base URLs
and model names out of application code. That leaves one question: how does the
control center change an environment variable?

It writes this file, and this file is loaded into `os.environ` when the Gateway
starts. So there is still exactly one source of truth — the environment — and
the GUI edits the thing that fills it, rather than a parallel config the code
would then have to reconcile.

Two deliberate properties:

* **A real environment variable wins.** Anything already set when the Gateway
  starts is left alone, so launching with `OPENAI_API_KEY=...` in the shell is
  not silently overridden by a stale saved value.
* **Secrets go out masked.** The file holds API keys; the endpoint that reads it
  must never hand them back to a renderer. Only whether a key is present.
"""

from __future__ import annotations

import os
from pathlib import Path

SECRET_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD")


def config_path() -> Path:
    configured = os.environ.get("MARVI_PROVIDER_CONFIG", "").strip()
    if configured:
        return Path(configured)
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(root) / "Marvi OS" / "providers.env"


def is_secret(name: str) -> bool:
    return any(marker in name.upper() for marker in SECRET_MARKERS)


def mask(value: str) -> str:
    """Enough to recognise a key, not enough to use one."""
    value = value.strip()
    return f"…{value[-4:]}" if len(value) > 8 else "set"


def read(path: Path | None = None) -> dict[str, str]:
    target = path or config_path()
    values: dict[str, str] = {}
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip()
    return values


def write(values: dict[str, str], path: Path | None = None) -> Path:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"{k}={v}" for k, v in sorted(values.items()) if v != "")
    target.write_text(
        "# Marvi OS provider settings. Written by the control center.\n" + body + "\n",
        encoding="utf-8",
    )
    return target


def load_into_environ(path: Path | None = None) -> int:
    """Apply saved settings, without clobbering the real environment."""
    applied = 0
    for name, value in read(path).items():
        if not os.environ.get(name, "").strip():
            os.environ[name] = value
            applied += 1
    return applied


def update(changes: dict[str, str], path: Path | None = None) -> dict[str, str]:
    """Save changes and apply them immediately, so no restart is needed.

    An empty value clears the setting, which is how the GUI disconnects a
    provider: remove the credential and it stops being configured.
    """
    values = read(path)
    for name, value in changes.items():
        name = name.strip()
        if not name:
            continue
        if value == "":
            values.pop(name, None)
            os.environ.pop(name, None)
        else:
            values[name] = value
            os.environ[name] = value
    write(values, path)
    return values


def visible(path: Path | None = None) -> dict[str, str]:
    """Saved settings, with secrets masked. Safe to send to a renderer."""
    return {
        name: (mask(value) if is_secret(name) else value)
        for name, value in read(path).items()
    }
