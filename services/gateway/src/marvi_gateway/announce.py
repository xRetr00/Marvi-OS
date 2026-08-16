"""Proactive speech.

Two different jobs need two different voices. The full-duplex session needs a
streaming model that can be interrupted mid-sentence, which is why Phase 3 pays
for VibeVoice on the GPU. A proactive announcement is the opposite: one short
sentence Marvi decided to say, with nobody waiting on a first token and nothing
to barge into. Paying streaming-GPU cost for that would be wrong, so
announcements use kyutai's PocketTTS on the CPU instead.

Measured on this machine at 24 kHz: 1.5 s to load, 0.811 RTF with a single
torch thread.

The audio is published into the same LiveKit room the desktop client is already
subscribed to, rather than played straight to the sound card. That matters:
Marvi's microphone is always live for the wake word, so a proactive sentence
played outside the room would be heard and transcribed as if the user had said
it. Going through the room means the Electron client's WebRTC echo cancellation
— the same mechanism Phase 3 relies on — cancels it.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .background import LoopThread

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "alba"
SPEAK_SAMPLE_RATE = 24_000
PUBLISH_TIMEOUT = 120.0
MAX_SPEECH_CHARS = 400


class AnnounceUnavailableError(Exception):
    """PocketTTS or the LiveKit transport is not available."""


def announce_enabled() -> bool:
    return os.environ.get("MARVI_ANNOUNCE", "1").strip().lower() not in ("0", "off", "false")


class Announcer:
    """One-shot CPU speech, published into the local LiveKit room."""

    def __init__(
        self,
        voice: str | None = None,
        room_url: str | None = None,
        room_name: str | None = None,
        token_factory: Any = None,
        loop: LoopThread | None = None,
    ) -> None:
        self.voice = voice or os.environ.get("MARVI_ANNOUNCE_VOICE", DEFAULT_VOICE)
        self.room_url = room_url or os.environ.get("LIVEKIT_URL", "ws://127.0.0.1:7880")
        self.room_name = room_name or os.environ.get("MARVI_LIVEKIT_ROOM", "marvi-os-local")
        self._token_factory = token_factory
        self._loop = loop
        self._model: Any = None
        self._voice_state: Any = None

    # -- synthesis -----------------------------------------------------------

    def _ensure_model(self) -> Any:
        if self._model is None:
            try:
                from pocket_tts import TTSModel
            except ImportError as exc:
                raise AnnounceUnavailableError("PocketTTS is not installed.") from exc
            try:
                import torch

                # ponytail: torch defaults to one thread here, which roughly
                # doubles synthesis time. Raise it for announcements only; the
                # GPU session is unaffected. Tune if it ever competes with the
                # voice path for CPU.
                torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
            except ImportError:
                pass
            self._model = TTSModel.load_model()
            self._voice_state = self._model.get_state_for_audio_prompt(self.voice)
        return self._model

    def synthesize(self, text: str) -> tuple[bytes, int]:
        """Render one sentence to 16-bit PCM."""
        spoken = (text or "").strip()[:MAX_SPEECH_CHARS]
        if not spoken:
            raise AnnounceUnavailableError("nothing to say")
        model = self._ensure_model()
        audio = model.generate_audio(self._voice_state, spoken)

        import numpy as np

        samples = audio.detach().cpu().numpy().astype("float32").reshape(-1)
        clipped = np.clip(samples, -1.0, 1.0)
        return (clipped * 32767.0).astype("<i2").tobytes(), int(model.sample_rate)

    # -- publishing ----------------------------------------------------------

    def _ensure_loop(self) -> LoopThread:
        if self._loop is None:
            self._loop = LoopThread(name="marvi-announce")
        return self._loop

    def _token(self) -> str:
        if self._token_factory is not None:
            return self._token_factory()
        from livekit import api

        return (
            api.AccessToken(
                os.environ.get("LIVEKIT_API_KEY", "devkey"),
                os.environ.get("LIVEKIT_API_SECRET", "secret"),
            )
            .with_identity("marvi-announcer")
            .with_name("Marvi")
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=self.room_name,
                    can_publish=True,
                    can_subscribe=False,
                )
            )
            .to_jwt()
        )

    async def _publish(self, pcm: bytes, rate: int) -> dict[str, Any]:
        from livekit import rtc

        room = rtc.Room()
        await room.connect(self.room_url, self._token())
        try:
            source = rtc.AudioSource(rate, 1)
            track = rtc.LocalAudioTrack.create_audio_track("marvi-announcement", source)
            await room.local_participant.publish_track(
                track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
            )
            # Push in 10 ms frames so playout paces naturally.
            frame_samples = rate // 100
            frame_bytes = frame_samples * 2
            for offset in range(0, len(pcm), frame_bytes):
                chunk = pcm[offset : offset + frame_bytes]
                if len(chunk) < frame_bytes:
                    chunk = chunk + b"\x00" * (frame_bytes - len(chunk))
                await source.capture_frame(
                    rtc.AudioFrame(
                        data=chunk,
                        sample_rate=rate,
                        num_channels=1,
                        samples_per_channel=frame_samples,
                    )
                )
            await source.wait_for_playout()
            return {"published": True, "seconds": round(len(pcm) / 2 / rate, 2)}
        finally:
            await room.disconnect()

    def speak(self, text: str) -> dict[str, Any]:
        """Synthesise and publish. Never raises into the caller's tick."""
        try:
            pcm, rate = self.synthesize(text)
        except Exception as exc:
            logger.warning("announcement synthesis failed: %s", exc)
            return {"published": False, "error": str(exc)[:200]}
        try:
            return self._ensure_loop().submit(self._publish(pcm, rate), timeout=PUBLISH_TIMEOUT)
        except Exception as exc:
            logger.warning("announcement publish failed: %s", exc)
            return {"published": False, "error": str(exc)[:200]}

    def close(self) -> None:
        if self._loop is not None:
            self._loop.stop()
            self._loop = None
