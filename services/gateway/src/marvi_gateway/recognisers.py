"""The local speech recognisers offered by the control center.

The agent has been able to run two recognisers since the Nemotron adapter
landed, chosen by `MARVI_STT_ENGINE`. Nothing offered the choice: the Voice
page printed the name of whichever one loaded, and the Settings page had a
lookahead slider and a device picker for an engine you could not pick. A
setting that exists and cannot be reached is the same as no setting, except
that it can also be wrong without anybody noticing.

This mirrors `voices` deliberately -- same catalog-from-JSON shape, same
`available()` question, same row for the picker -- because the two pages sit
next to each other and should not need two mental models between them.

## What `available` means here

Not "the file is on disk" but "this would actually load". Parakeet is
in-process and ships with the agent, so it is always available. Nemotron is
parakeet.cpp: a native DLL, a CUDA runtime beside it, and a GGUF model, any of
which can be missing on a machine that never installed it. Offering it anyway
would put a recogniser in the picker that silently falls back to the other one
the moment it is chosen.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

ENGINE_ENV = "MARVI_STT_ENGINE"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class Recogniser:
    id: str
    name: str
    description: str
    runtime: str
    install_to: str
    model_file: str
    measured: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "runtime": self.runtime,
            "available": self.available(),
            "measured": self.measured,
        }

    def available(self) -> bool:
        if self.runtime == "in-process":
            # Ships with the agent; there is no separate install to miss.
            return True
        from .setup.catalog import install_root

        if not self.install_to or not self.model_file:
            return False
        root = install_root()
        # All three, because the adapter needs all three. The weights alone
        # would put the recogniser in the picker and then fall back to the
        # default the moment it was chosen, and cuBLAS is the one that fails
        # latest and least legibly -- the library loads and dies on the first
        # frame of audio.
        return (
            (root / self.install_to / self.model_file).is_file()
            and (root / "runtimes/parakeet-cpp/lib/parakeet.dll").is_file()
            and (root / "runtimes/parakeet-cpp/cudart/cudart64_12.dll").is_file()
        )


@lru_cache(maxsize=1)
def catalog() -> tuple[str, tuple[Recogniser, ...]]:
    raw = json.loads((_repo_root() / "config" / "stt-engines.json").read_text("utf-8"))
    found = tuple(
        Recogniser(
            id=str(item["id"]),
            name=str(item["name"]),
            description=str(item.get("description", "")),
            runtime=str(item.get("runtime", "in-process")),
            install_to=str(item.get("install_to", "")),
            model_file=str(item.get("model_file", "")),
            measured=dict(item.get("measured", {})),
        )
        for item in raw.get("engines", ())
    )
    return str(raw.get("default_engine", "parakeet-tdt")), found


def engines() -> list[Recogniser]:
    return list(catalog()[1])


def selected() -> str:
    """The chosen recogniser, or the default when the choice cannot be met."""
    default, offered = catalog()
    chosen = os.environ.get(ENGINE_ENV, "").strip().lower()
    return chosen if any(item.id == chosen for item in offered) else default
