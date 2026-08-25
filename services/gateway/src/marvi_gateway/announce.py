"""One-shot local speech for ARC, Room events, and Chat Read Aloud.

This is deliberately not the LiveKit voice path. A proactive sentence and a
finished Chat response need synthesis, cancellation, and the selected Windows
speaker; they do not need a room, microphone, VAD, STT, interruption, or an
agent job. PocketTTS renders on CPU and python-sounddevice writes the resulting
PCM to PortAudio.

Direct speaker playback can be heard by the always-on wake listener. A small
marker under Marvi's state directory tells that process not to score Marvi's
own audio. It never contains speech or user content.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from . import paths

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "alba"
SPEAK_SAMPLE_RATE = 24_000
MAX_PROACTIVE_CHARS = 400
MAX_READ_ALOUD_CHARS = 12_000
SYNTHESIS_CHUNK_CHARS = 400
FRAME_MILLISECONDS = 20


class AnnounceUnavailableError(Exception):
    """PocketTTS or the local output device is unavailable."""


def announce_enabled() -> bool:
    return os.environ.get("MARVI_ANNOUNCE", "1").strip().lower() not in ("0", "off", "false")


def marker_path() -> Path:
    return paths.root() / "state" / "announcing.json"


def pocket_cache_dir() -> Path:
    """The Hugging Face cache Setup and runtime both own and can remove."""
    return paths.models_dir() / "pocket-tts" / "huggingface"


def _chunks(text: str, limit: int = SYNTHESIS_CHUNK_CHARS) -> list[str]:
    """Split prose at sentence/word boundaries without dropping any text."""
    compact = " ".join((text or "").split())
    if not compact:
        return []
    chunks: list[str] = []
    current = ""
    for word in compact.split():
        if len(word) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(word[offset : offset + limit] for offset in range(0, len(word), limit))
            continue
        proposed = f"{current} {word}".strip()
        if current and len(proposed) > limit:
            chunks.append(current)
            current = word
        else:
            current = proposed
    if current:
        chunks.append(current)
    return chunks


class SoundDevicePlayer:
    """Blocking PCM output through PortAudio's selected Windows endpoint."""

    def __init__(self, device: str | None = None) -> None:
        self.device = device if device is not None else os.environ.get("MARVI_ANNOUNCE_DEVICE", "")

    def play(self, pcm: bytes, rate: int, cancelled: threading.Event) -> bool:
        try:
            import sounddevice
        except ImportError as exc:
            raise AnnounceUnavailableError("sounddevice is not installed") from exc

        frame_bytes = max(1, int(rate * FRAME_MILLISECONDS / 1000)) * 2
        chosen: str | None = self.device.strip() or None
        try:
            with sounddevice.RawOutputStream(
                samplerate=rate,
                channels=1,
                dtype="int16",
                blocksize=frame_bytes // 2,
                device=chosen,
            ) as stream:
                for offset in range(0, len(pcm), frame_bytes):
                    if cancelled.is_set():
                        return False
                    stream.write(pcm[offset : offset + frame_bytes])
        except Exception as exc:
            label = repr(chosen) if chosen else "the default output"
            raise AnnounceUnavailableError(f"could not play through {label}: {exc}") from exc
        return not cancelled.is_set()


def output_devices() -> list[dict[str, object]]:
    """PortAudio output endpoints, deduplicated by their stable names."""
    try:
        import sounddevice

        devices = sounddevice.query_devices()
        default_name = str(sounddevice.query_devices(kind="output").get("name", "")).strip()
    except Exception as exc:  # pragma: no cover - depends on host audio
        logger.warning("cannot list output devices: %s", exc)
        return []
    names: list[str] = []
    for device in devices:
        if int(device.get("max_output_channels", 0)) < 1:
            continue
        name = str(device.get("name", "")).strip()
        if name and name not in names:
            names.append(name)
    kept = [
        name
        for name in names
        if not any(other != name and other.startswith(name) for other in names)
    ]
    return [
        {
            "name": name,
            "label": " ".join(name.split())[:64],
            "default": bool(default_name)
            and (name == default_name or name.startswith(default_name)),
        }
        for name in kept
    ]


class Announcer:
    """Shared, cancellable PocketTTS synthesis and local playback service."""

    def __init__(self, voice: str | None = None, player: Any = None) -> None:
        self.voice = voice or os.environ.get("MARVI_ANNOUNCE_VOICE", DEFAULT_VOICE)
        self.player = player or SoundDevicePlayer()
        self._model: Any = None
        self._voice_state: Any = None
        self._serial = threading.Lock()
        self._state = threading.Lock()
        self._current: threading.Event | None = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            cache = pocket_cache_dir()
            cache.mkdir(parents=True, exist_ok=True)
            # Setup must own every downloaded byte so Remove is honest. Do not
            # inherit a process-wide cache elsewhere on disk.
            os.environ["HF_HUB_CACHE"] = str(cache)
            with contextlib.suppress(ImportError):
                # Another Gateway dependency may have imported HF first; its
                # constants are initialised at import time rather than per call.
                from huggingface_hub import constants as hf_constants

                hf_constants.HF_HUB_CACHE = str(cache)
            try:
                from pocket_tts import TTSModel
            except ImportError as exc:
                raise AnnounceUnavailableError("PocketTTS is not installed; open Setup") from exc
            try:
                import torch

                torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
            except ImportError:
                pass
            self._model = TTSModel.load_model()
            self._voice_state = self._model.get_state_for_audio_prompt(self.voice)
        return self._model

    def synthesize(self, text: str) -> tuple[bytes, int]:
        spoken = (text or "").strip()
        if not spoken:
            raise AnnounceUnavailableError("nothing to say")
        model = self._ensure_model()
        audio = model.generate_audio(self._voice_state, spoken)

        import numpy as np

        samples = audio.detach().cpu().numpy().astype("float32").reshape(-1)
        clipped = np.clip(samples, -1.0, 1.0)
        return (clipped * 32767.0).astype("<i2").tobytes(), int(model.sample_rate)

    def prepare(self) -> dict[str, Any]:
        """Download/load the configured model and voice without playing audio."""
        started = time.perf_counter()
        self._ensure_model()
        return {
            "ready": True,
            "voice": self.voice,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    @contextlib.contextmanager
    def _wake_guard(self, purpose: str):
        marker = marker_path()
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(
                json.dumps({"pid": os.getpid(), "started_at": time.time(), "purpose": purpose}),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("could not arm wake suppression: %s", exc)
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                marker.unlink()

    def stop(self) -> bool:
        with self._state:
            current = self._current
            if current is None:
                return False
            current.set()
            logger.info("announcement cancellation requested")
            return True

    def speak(self, text: str, purpose: str = "proactive") -> dict[str, Any]:
        """Replace current one-shot speech, synthesize, and play to completion."""
        limit = MAX_READ_ALOUD_CHARS if purpose == "read_aloud" else MAX_PROACTIVE_CHARS
        spoken = " ".join((text or "").split())[:limit]
        pieces = _chunks(spoken)
        if not pieces:
            return {"played": False, "error": "nothing to say", "cancelled": False}

        cancelled = threading.Event()
        with self._state:
            if self._current is not None:
                self._current.set()
            self._current = cancelled

        started = time.perf_counter()
        seconds = 0.0
        logger.info(
            "announcement started",
            extra={
                "marvi_purpose": purpose,
                "marvi_chars": len(spoken),
                "marvi_chunks": len(pieces),
            },
        )
        try:
            with self._serial:
                if cancelled.is_set():
                    logger.info("announcement cancelled before synthesis")
                    return {"played": False, "cancelled": True, "error": ""}
                for piece in pieces:
                    pcm, rate = self.synthesize(piece)
                    seconds += len(pcm) / 2 / rate
                    with self._wake_guard(purpose):
                        completed = self.player.play(pcm, rate, cancelled)
                    if not completed:
                        logger.info(
                            "announcement cancelled during playback",
                            extra={"marvi_purpose": purpose},
                        )
                        return {"played": False, "cancelled": True, "error": ""}
        except Exception as exc:
            logger.warning("announcement failed: %s", exc, exc_info=True)
            return {"played": False, "cancelled": False, "error": str(exc)[:200]}
        finally:
            with self._state:
                if self._current is cancelled:
                    self._current = None

        logger.info(
            "announcement played",
            extra={
                "marvi_purpose": purpose,
                "marvi_chars": len(spoken),
                "marvi_chunks": len(pieces),
                "marvi_audio_seconds": round(seconds, 2),
                "marvi_latency_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return {"played": True, "cancelled": False, "seconds": round(seconds, 2)}

    def close(self) -> None:
        self.stop()
