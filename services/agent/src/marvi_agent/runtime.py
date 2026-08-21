"""What the voice worker needs before it can speak.

No provider is named here. The Agent runs in its own Python environment and
must not carry a second copy of the provider table — two copies drift, and the
one that drifts is always the one the user did not edit.

Instead it asks the Gateway, over the same loopback channel it already uses for
tools, and gets back whatever the user configured in the control center. The
registry in `marvi_gateway.providers` stays the single source of truth.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
from livekit.plugins import openai

RESOLVE_TIMEOUT = 8.0


class VoiceStackPendingError(RuntimeError):
    """Raised until the native-Windows STT/TTS bakeoff selects both adapters."""


class ProviderUnavailableError(RuntimeError):
    """The Gateway could not name a usable provider for the voice path."""


def gateway_base_url() -> str:
    return os.environ.get("MARVI_GATEWAY_URL", "http://127.0.0.1:8765").rstrip("/")


@dataclass(frozen=True, slots=True)
class AgentConfig:
    api_key: str
    model: str
    base_url: str
    provider: str = "unknown"

    @classmethod
    def from_gateway(cls, client: httpx.Client | None = None) -> AgentConfig:
        http = client or httpx.Client(timeout=RESOLVE_TIMEOUT)
        try:
            response = http.get(f"{gateway_base_url()}/providers/voice")
            if response.status_code == 503:
                raise ProviderUnavailableError(
                    "No provider is configured. Connect one in the Marvi control center."
                )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"Marvi Gateway is unreachable: {exc}") from exc
        finally:
            if client is None:
                http.close()

        if not body.get("base_url") or not body.get("model"):
            raise ProviderUnavailableError("Gateway returned an incomplete provider")
        return cls(
            api_key=body.get("api_key") or "local",
            model=body["model"],
            base_url=body["base_url"],
            provider=body.get("provider", "unknown"),
        )


def build_llm(config: AgentConfig) -> openai.LLM:
    """Every provider Marvi speaks to on the voice path is OpenAI-compatible."""
    return openai.LLM(model=config.model, base_url=config.base_url, api_key=config.api_key)


def build_local_turn_detector() -> str:
    """End of turn from VAD silence, decided on this machine.

    It used to return `inference.TurnDetector(version="v1-mini")` under a
    docstring calling it "the local CPU model". It is not: it takes base_url,
    api_key and api_secret, and it asks LiveKit Inference. Marvi runs against a
    self-hosted LiveKit with local keys, so it could never reach it -- and the
    failure was silent in exactly the worst way.

    End of turn never resolved, so the STT stream was never flushed, so no
    FINAL_TRANSCRIPT was ever emitted. Speech was recognised perfectly and
    stayed as interim results forever:

        stt (partial): Hey Morvey, are you listening to me?  Are you here?

    and the model was never called, because as far as the session was
    concerned the user had not stopped speaking.

    "vad" is a first-class mode and it is local. A cloud dependency in the turn
    loop of a local-first assistant was the wrong choice regardless of whether
    it worked.
    """
    return "vad"


def require_selected_voice_adapters(stt: object | None, tts: object | None) -> None:
    if stt is None or tts is None:
        raise VoiceStackPendingError(
            "Native streaming STT/TTS adapters are not selected yet; run the documented bakeoff"
        )
