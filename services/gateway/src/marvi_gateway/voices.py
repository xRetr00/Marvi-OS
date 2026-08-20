"""Which voices Marvi can speak in.

The TTS installer downloads twenty-five of them and nothing in the app listed
any: the voice was an environment variable holding a filename, so choosing one
meant knowing the naming convention and typing it exactly.

The names carry more than they look like. `en-Carter_man.pt` is a language, a
name and a gender, in a convention the model ships with — so the picker can
show "Carter · English · man" instead of a filename, and can be filtered by
any of those.

Speaker embeddings, not audio: there is no sample to play, so these rows carry
no preview. Producing one would mean running the TTS engine, which lives in the
Agent's process and its own Python environment.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import paths
from .logs import get_logger

log = get_logger("voice")

#: Where the TTS installer puts them. One place, derived from the same app data
#: root everything else uses.
VOICES_DIR = Path("models/tts/vibevoice-realtime-0.5b/voices")

#: The variable the Agent reads when it builds the TTS adapter.
VOICE_ENV = "MARVI_TTS_VOICE"

#: The prefixes the shipped voices use. Only for display -- an unknown prefix
#: shows as itself rather than being dropped, because a voice that exists must
#: be selectable whether or not this table knows its language.
LANGUAGES = {
    "en": "English",
    "de": "German",
    "fr": "French",
    "it": "Italian",
    "jp": "Japanese",
    "kr": "Korean",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "es": "Spanish",
    "in": "Indian English",
    "zh": "Chinese",
    "ru": "Russian",
    "tr": "Turkish",
}


@dataclass(frozen=True)
class Voice:
    """One installed voice, as the picker needs it."""

    #: What goes in the environment variable: the filename without .pt.
    id: str
    name: str
    language: str
    gender: str

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


def _parse(stem: str) -> Voice:
    """`en-Carter_man` -> Carter, English, man.

    Tolerant on purpose. A voice whose name does not fit the convention is
    still installed and still speakable, so it comes back named after its own
    file rather than being hidden.
    """
    language, _, rest = stem.partition("-")
    if not rest:
        return Voice(id=stem, name=stem, language="", gender="")
    name, _, gender = rest.partition("_")
    return Voice(
        id=stem,
        name=name or stem,
        language=LANGUAGES.get(language.lower(), language),
        gender=gender,
    )


def voices_dir() -> Path:
    return paths.root() / VOICES_DIR


def installed() -> list[Voice]:
    """Every downloaded voice, or an empty list if none are.

    Empty is a real answer -- the TTS model is a multi-gigabyte download and a
    fresh install has none -- so the caller says "install the voice model"
    rather than treating it as an error.
    """
    directory = voices_dir()
    try:
        stems = sorted(path.stem for path in directory.glob("*.pt"))
    except OSError as exc:
        log.warning("could not read the voices directory: %s", exc)
        return []
    return [_parse(stem) for stem in stems]


def selected() -> str:
    """The configured voice, whether or not it is installed.

    Reported as configured rather than silently corrected: a voice that was
    chosen and then deleted should show as missing, not as though the choice
    never happened.
    """
    return os.environ.get(VOICE_ENV, "").strip()
