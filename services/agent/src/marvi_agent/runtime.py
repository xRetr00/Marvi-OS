from __future__ import annotations

import os
from dataclasses import dataclass

from livekit.agents import inference
from livekit.plugins import openai

OPENCODE_GO_BASE_URL = "https://opencode.ai/zen/go/v1"


class VoiceStackPendingError(RuntimeError):
    """Raised until the native-Windows STT/TTS bakeoff selects both adapters."""


@dataclass(frozen=True, slots=True)
class AgentConfig:
    api_key: str
    model: str = "deepseek-v4-flash"
    base_url: str = OPENCODE_GO_BASE_URL

    @classmethod
    def from_env(cls) -> AgentConfig:
        api_key = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
        if not api_key:
            raise ValueError("OPENCODE_GO_API_KEY is required")

        return cls(
            api_key=api_key,
            model=os.environ.get("MARVI_LLM_MODEL", "deepseek-v4-flash").strip(),
            base_url=os.environ.get("MARVI_LLM_BASE_URL", OPENCODE_GO_BASE_URL).strip(),
        )


def build_llm(config: AgentConfig) -> openai.LLM:
    """Build the documented OpenAI-compatible adapter for OpenCode Go."""
    return openai.LLM(model=config.model, base_url=config.base_url, api_key=config.api_key)


def build_local_turn_detector() -> inference.TurnDetector:
    """Pin end-of-turn inference to the local CPU model; never auto-select cloud v1."""
    return inference.TurnDetector(version="v1-mini")


def require_selected_voice_adapters(stt: object | None, tts: object | None) -> None:
    if stt is None or tts is None:
        raise VoiceStackPendingError(
            "Native streaming STT/TTS adapters are not selected yet; run the documented bakeoff"
        )
