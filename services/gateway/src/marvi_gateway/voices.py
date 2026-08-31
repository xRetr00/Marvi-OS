"""The local TTS engines and voices offered by the control center."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

ENGINE_ENV = "MARVI_TTS_ENGINE"
VOICE_ENV = "MARVI_TTS_VOICE"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    language: str
    gender: str

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Engine:
    id: str
    name: str
    description: str
    runtime: str
    default_voice: str
    install_to: str
    project: str
    voices: tuple[Voice, ...]

    def as_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "runtime": self.runtime,
            "default_voice": self.default_voice,
            "available": self.available(),
        }

    def available(self) -> bool:
        from .setup.catalog import install_root

        target = install_root() / self.install_to
        if self.id == "kokoro":
            return (target / "kokoro-v1_0.pth").is_file()
        runtime = _repo_root() / self.project / ".venv"
        return runtime.is_dir() and (target / ".marvi-revision").is_file()


@lru_cache(maxsize=1)
def catalog() -> tuple[str, tuple[Engine, ...]]:
    raw = json.loads((_repo_root() / "config" / "tts-engines.json").read_text("utf-8"))
    engines = tuple(
        Engine(
            id=str(item["id"]),
            name=str(item["name"]),
            description=str(item.get("description", "")),
            runtime=str(item.get("runtime", "isolated")),
            default_voice=str(item["default_voice"]),
            install_to=str(item.get("install_to", "")),
            project=str(item.get("project", "")),
            voices=tuple(
                Voice(
                    id=str(voice["id"]),
                    name=str(voice["name"]),
                    language=str(voice.get("language", "")),
                    gender=str(voice.get("gender", "")),
                )
                for voice in item.get("voices", ())
            ),
        )
        for item in raw.get("engines", ())
    )
    return str(raw.get("default_engine", "kokoro")), engines


def engines() -> list[Engine]:
    return list(catalog()[1])


def selected_engine() -> str:
    default, offered = catalog()
    chosen = os.environ.get(ENGINE_ENV, "").strip()
    return chosen if any(engine.id == chosen for engine in offered) else default


def installed(engine: str | None = None) -> list[Voice]:
    wanted = engine or selected_engine()
    found = next((item for item in catalog()[1] if item.id == wanted), None)
    return list(found.voices) if found else []


def selected() -> str:
    return os.environ.get(VOICE_ENV, "").strip()


def resolved_voice(engine: str | None = None, voice: str | None = None) -> str:
    wanted_engine = engine or selected_engine()
    found = next((item for item in catalog()[1] if item.id == wanted_engine), None)
    if found is None:
        return ""
    wanted_voice = selected() if voice is None else voice
    if any(item.id == wanted_voice for item in found.voices):
        return wanted_voice
    return found.default_voice


# Compatibility for the language policy and older tests. The source of truth is
# now the shared JSON catalog, not a second tuple that can drift from the UI.
KOKORO_VOICES = tuple(
    (voice.id, voice.name, voice.language, voice.gender)
    for engine in catalog()[1]
    if engine.id == "kokoro"
    for voice in engine.voices
)
