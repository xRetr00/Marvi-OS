"""What an installation that predates the current speech engine still carries.

Marvi used to speak with VibeVoice. It now speaks with Kokoro, and an install
that has been running since before that swap is left holding two things.

**A setting that names a voice which no longer exists.** `en-Carter_man` was a
VibeVoice speaker prompt. The Agent already refuses to fail on it -- it falls
back and says so -- but falling back on every session forever is not the same as
being fixed, and the Settings pane would go on showing a choice that cannot be
honoured. That one is rewritten here, because there is exactly one right answer
and no judgement involved.

**Model nothing loads.** Reported here; the daily storage pass removes it,
because nothing loads it and nothing can -- see `storage.leftovers`.
"""

from __future__ import annotations

import logging
import os

from .storage import Reclaimable, leftovers

log = logging.getLogger(__name__)

VOICE_ENV = "MARVI_TTS_VOICE"


def reclaimable() -> list[Reclaimable]:
    """What previous engines left behind. Never deletes anything."""
    return leftovers()


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
