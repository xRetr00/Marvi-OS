"""Voices Marvi learned from a recording, rather than ones she shipped with.

Two of the three local engines are voice-cloning models, and the catalog was
hiding it. CuteTTS has no voice bank at all -- the picker's one entry, "Cute
Reference", is the single demo recording upstream bundles, and the host has
always run it in `voice_clone` mode against that file. VoXtream's twelve
"voices" are twelve prompt recordings in `assets/audio` used exactly the same
way. So the honest answer to "how do I get more CuteTTS voices" is that there
are none to get: you supply the voice.

This turns that from a fact about the code into a feature. A recording goes in,
a voice comes out, and it appears in the same picker beside the built-in ones
because as far as both engines are concerned it is the same kind of thing.

## Why the engine owns the voice

A cloned voice is a reference recording plus the model that interprets it. The
same wav through CuteTTS and through VoXtream is two different voices, and
neither is portable to Kokoro, which has a fixed bank and no reference input at
all. Storing clones under the engine keeps the picker honest: switch engine and
you see the voices that engine can actually produce, rather than a list that
half-works.

## What is checked, and what is not

Format is checked, because a wav the engine cannot read fails deep inside a
sidecar and surfaces as "TTS died". Quality is not: there is no way to tell a
good reference from a bad one without synthesising, and refusing a recording
because it is noisy would be a guess presented as a rule. Short and long are
bounded because both are known to produce nonsense -- under a second there is
not enough voice to copy, and past a minute the engines truncate anyway.
"""

from __future__ import annotations

import json
import re
import shutil
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Engines whose sidecar takes a reference recording. Read from the catalog
#: rather than listed here, so adding a cloning engine is a config change.
CLONING_KEY = "cloning"

#: The reference window both engines are built around. Their own bundled
#: prompts run 3.7 to 10.3 seconds, which is the shape to aim for; the bounds
#: are wider than that because a rule should refuse what cannot work, not what
#: is merely unlike the examples.
SHORTEST = 1.0
LONGEST = 60.0

#: Sample rates the engines resample from without complaint. Anything below
#: telephone quality has already lost what makes a voice recognisable.
LOWEST_RATE = 8_000

MAX_BYTES = 32 * 1024 * 1024

_ID = re.compile(r"[^a-z0-9]+")


def _root() -> Path:
    from .setup.catalog import install_root

    return install_root() / "voices"


@dataclass(frozen=True)
class Clone:
    id: str
    name: str
    engine: str
    seconds: float

    def as_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "engine": self.engine,
            "seconds": round(self.seconds, 2),
            # The picker shows built-in and cloned voices in one list, and a
            # cloned voice is the only kind that can be deleted.
            "cloned": True,
        }


class CloneError(ValueError):
    """A recording that cannot become a voice, with the reason a person needs."""


#: The announcer, which is not in the TTS catalog because it is not a
#: conversational engine -- it renders one-shot proactive lines and Read Aloud
#: on the CPU, cold, and is deliberately not kept warm.
#:
#: It clones the same way: PocketTTS conditions on either a built-in embedding
#: or an audio file, so a recording is a voice with no extra API. Sharing this
#: store means the announcer gets the format checks, the deletion and the UI
#: that already exist rather than a second half of each.
ANNOUNCER = "pocket"


def engines() -> list[str]:
    """The engines that can speak in a cloned voice."""
    from .voices import catalog

    return [item.id for item in catalog()[1] if item.cloning] + [ANNOUNCER]


def _index() -> dict[str, Any]:
    path = _root() / "index.json"
    if not path.is_file():
        return {}
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _write_index(index: dict[str, Any]) -> None:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def saved(engine: str = "") -> list[Clone]:
    """Cloned voices, for one engine or all of them."""
    index = _index()
    found: list[Clone] = []
    for key, row in sorted(index.items()):
        if not isinstance(row, dict):
            continue
        owner = str(row.get("engine", ""))
        if engine and owner != engine:
            continue
        if not path(owner, str(row.get("id", key))).is_file():
            # Recorded but the file is gone. Skipped rather than offered: a
            # voice that cannot be spoken in is worse in a picker than absent.
            continue
        found.append(
            Clone(
                id=str(row.get("id", key)),
                name=str(row.get("name", key)),
                engine=owner,
                seconds=float(row.get("seconds", 0.0)),
            )
        )
    return found


def path(engine: str, voice: str) -> Path:
    return _root() / engine / f"{voice}.wav"


def _identifier(name: str, engine: str) -> str:
    base = _ID.sub("-", name.strip().lower()).strip("-") or "voice"
    taken = {clone.id for clone in saved(engine)}
    if base not in taken:
        return base
    number = 2
    while f"{base}-{number}" in taken:
        number += 1
    return f"{base}-{number}"


def inspect(audio: bytes) -> float:
    """The recording's length, or the reason it cannot be used."""
    import io

    if len(audio) > MAX_BYTES:
        raise CloneError("that recording is larger than 32 MB")
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            rate, frames, width = (
                source.getframerate(),
                source.getnframes(),
                source.getsampwidth(),
            )
    except (wave.Error, EOFError, OSError) as exc:
        raise CloneError(f"that is not a WAV file Marvi can read ({exc})") from exc
    if width != 2:
        raise CloneError("the recording must be 16-bit PCM")
    if rate < LOWEST_RATE:
        raise CloneError(f"the recording is {rate} Hz; {LOWEST_RATE} Hz is the minimum")
    seconds = frames / rate if rate else 0.0
    if seconds < SHORTEST:
        raise CloneError(f"the recording is {seconds:.1f}s; at least {SHORTEST:.0f}s is needed")
    if seconds > LONGEST:
        raise CloneError(f"the recording is {seconds:.0f}s; {LONGEST:.0f}s is the most usable")
    return seconds


def add(engine: str, name: str, audio: bytes) -> Clone:
    """Keep a recording as a voice this engine can speak in."""
    if engine not in engines():
        raise CloneError(f"{engine} cannot speak in a cloned voice")
    seconds = inspect(audio)
    voice = _identifier(name, engine)
    target = path(engine, voice)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(audio)
    index = _index()
    index[f"{engine}/{voice}"] = {
        "id": voice,
        "name": name.strip() or voice,
        "engine": engine,
        "seconds": seconds,
    }
    _write_index(index)
    return Clone(id=voice, name=name.strip() or voice, engine=engine, seconds=seconds)


def remove(engine: str, voice: str) -> bool:
    """Forget a cloned voice. The recording goes with it."""
    index = _index()
    key = f"{engine}/{voice}"
    if key not in index:
        return False
    del index[key]
    _write_index(index)
    target = path(engine, voice)
    target.unlink(missing_ok=True)
    with_engine = target.parent
    if with_engine.is_dir() and not any(with_engine.iterdir()):
        shutil.rmtree(with_engine, ignore_errors=True)
    return True
