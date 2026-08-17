"""Every path Marvi writes to, in one place.

There used to be two directories: `Marvi-OS` for models and binaries, because
the PowerShell installers created it, and `Marvi OS` for logs, databases and
identity, because nine separate modules each wrote their own literal. Two
folders with nearly the same name is confusing to look at and a nuisance to
back up, and a space in a path is a nuisance in every shell.

**`Marvi-OS` is the one root.** Everything below derives from it, so there is
nothing left to keep in sync.

The old location is migrated on first use rather than abandoned: someone's
memory, their journal and their identity files are in there, and silently
starting fresh would look exactly like data loss.
"""

from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path

#: The display name. A product name, not a path — those are separate concerns
#: and conflating them is how the space got into the path in the first place.
PRODUCT = "Marvi OS"

FOLDER = "Marvi-OS"
LEGACY_FOLDER = "Marvi OS"


def _home() -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(root)


def root() -> Path:
    """Everything Marvi owns lives here."""
    configured = os.environ.get("MARVI_HOME", "").strip()
    return Path(configured) if configured else _home() / FOLDER


def legacy_root() -> Path:
    return _home() / LEGACY_FOLDER


def _from_env(name: str, *parts: str) -> Path:
    """A path, overridable by one environment variable, defaulting under root."""
    configured = os.environ.get(name, "").strip()
    return Path(configured) if configured else root().joinpath(*parts)


def logs_dir() -> Path:
    return _from_env("MARVI_LOG_DIR", "logs")


def identity_dir() -> Path:
    return _from_env("MARVI_IDENTITY_DIR")


def journal_db() -> Path:
    return _from_env("MARVI_JOURNAL_DB", "journal.sqlite3")


def memory_db() -> Path:
    return _from_env("MARVI_MEMORY_DB", "memory.sqlite3")


def chat_db() -> Path:
    return _from_env("MARVI_CHAT_DB", "chat.sqlite3")


def provider_config() -> Path:
    return _from_env("MARVI_PROVIDER_CONFIG", "providers.env")


def token_store() -> Path:
    return _from_env("MARVI_TOKEN_STORE", "tokens.bin")


def audit_log() -> Path:
    return _from_env("MARVI_AUDIT_LOG", "audit.jsonl")


def vision_dir() -> Path:
    return _from_env("MARVI_VISION_DIR", "vision")


def models_dir() -> Path:
    return _from_env("MARVI_MODEL_ROOT", "models")


def runtime_dir() -> Path:
    return _from_env("MARVI_RUNTIME_ROOT", "runtime")


def skills_dir() -> Path:
    return _from_env("MARVI_SKILLS_DIR", "skills")


def mcp_config() -> Path:
    return _from_env("MARVI_MCP_CONFIG", "mcp.json")


# -- migration ----------------------------------------------------------------

#: Marker so the move is attempted once rather than on every start.
MIGRATED = ".migrated-from-marvi-os"


def migrate_legacy(force: bool = False) -> list[str]:
    """Move anything left in the old `Marvi OS` folder into `Marvi-OS`.

    Moved rather than copied so there is one copy and no doubt which is live,
    but **never overwriting**: if a name exists in both, the newer root wins and
    the old file is left where it is for the user to look at. Guessing which of
    two journals is the real one is not a decision to make silently.
    """
    old, new = legacy_root(), root()
    if old == new or not old.exists():
        return []
    marker = new / MIGRATED
    if marker.exists() and not force:
        return []

    new.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for item in old.iterdir():
        destination = new / item.name
        if destination.exists():
            continue
        try:
            shutil.move(str(item), str(destination))
            moved.append(item.name)
        except OSError:
            # A locked file is not worth failing startup over; it stays put and
            # the next run tries again.
            continue

    try:
        marker.write_text(
            "Contents were moved here from the old 'Marvi OS' folder.\n"
            "Delete that folder once you are happy nothing is missing.\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return moved


def describe() -> dict[str, str]:
    """Every path, for Doctor and `marvi doctor`."""
    return {
        "root": str(root()),
        "logs": str(logs_dir()),
        "identity": str(identity_dir()),
        "journal": str(journal_db()),
        "memory": str(memory_db()),
        "chat": str(chat_db()),
        "providers": str(provider_config()),
        "tokens": str(token_store()),
        "audit": str(audit_log()),
        "vision": str(vision_dir()),
        "models": str(models_dir()),
        "runtime": str(runtime_dir()),
        "skills": str(skills_dir()),
        "mcp": str(mcp_config()),
    }
