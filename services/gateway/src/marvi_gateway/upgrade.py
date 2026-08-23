"""What an installation that predates the current speech engine still carries.

Marvi used to speak with VibeVoice. It now speaks with Kokoro, and an install
that has been running since before that swap is left holding two things.

**A setting that names a voice which no longer exists.** `en-Carter_man` was a
VibeVoice speaker prompt. The Agent already refuses to fail on it -- it falls
back and says so -- but falling back on every session forever is not the same as
being fixed, and the Settings pane would go on showing a choice that cannot be
honoured. That one is rewritten here, because there is exactly one right answer
and no judgement involved.

**Two gigabytes of model nothing loads.** That is not rewritten, it is reported.
Deleting two gigabytes of somebody's disk without asking is not a migration, it
is a decision, and it is theirs -- the files are re-downloadable but the choice
of when to spend the bandwidth is not Marvi's to make. So it appears as
reclaimable space with a command beside it.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)

#: What previous engines left behind.
#:
#: Both halves of the speech stack were replaced: VibeVoice by Kokoro, and the
#: Nemotron export the Rust sidecar drove by a Parakeet ONNX export. Neither is
#: loaded by anything now, and together they are the better part of five
#: gigabytes.
RETIRED_MODELS = (
    "models/tts/vibevoice-realtime-0.5b",
    "models/stt/nemotron-3.5",
)

VOICE_ENV = "MARVI_TTS_VOICE"

RETIRED_WHY = {
    "models/tts/vibevoice-realtime-0.5b": "the previous speech engine, replaced by Kokoro",
    "models/stt/nemotron-3.5": "the previous recogniser, replaced by Parakeet",
}


@dataclass(frozen=True)
class Reclaimable:
    """A directory left behind by something Marvi no longer runs."""

    path: Path
    bytes: int
    why: str

    @property
    def gigabytes(self) -> float:
        return self.bytes / 1024**3


def _size(directory: Path) -> int:
    total = 0
    for path in directory.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def reclaimable() -> list[Reclaimable]:
    """Model directories nothing loads any more. Never deletes anything."""
    found = []
    for relative in RETIRED_MODELS:
        directory = paths.root() / relative
        if not directory.is_dir():
            continue
        found.append(
            Reclaimable(
                path=directory,
                bytes=_size(directory),
                why=RETIRED_WHY.get(relative, "no longer loaded"),
            )
        )
    return found


def stale_voice(configured: str, offered: list[str]) -> str | None:
    """The voice to switch to, or None if the configured one is fine.

    Only when the configured name is unmistakably from the old engine. An empty
    setting means "use the default" and is not stale; an unrecognised name that
    looks like a current one might be a voice added in a version this code has
    not seen, and rewriting that would take a choice away rather than repair
    one.
    """
    configured = configured.strip()
    if not configured or configured in offered:
        return None
    # VibeVoice named speakers `language-Name_gender`; Kokoro uses `af_heart`.
    if "-" not in configured:
        return None
    return offered[0] if offered else None


def run() -> list[str]:
    """Apply what can be applied. Returns a line per thing done or found."""
    from . import voices
    from .providers import config as provider_config

    notes: list[str] = []

    offered = [voice.id for voice in voices.installed()]
    configured = os.environ.get(VOICE_ENV, "").strip()
    replacement = stale_voice(configured, offered)
    if replacement:
        provider_config.update({VOICE_ENV: replacement})
        os.environ[VOICE_ENV] = replacement
        notes.append(f"voice {configured!r} is from the previous engine; now {replacement}")
        log.info("migrated the configured voice from %s to %s", configured, replacement)

    for entry in reclaimable():
        notes.append(
            f"{entry.gigabytes:.1f} GB in {entry.path.name} is {entry.why} "
            f"— remove it with `marvi models prune`"
        )
        log.info("reclaimable: %s (%.1f GB)", entry.path, entry.gigabytes)

    return notes
