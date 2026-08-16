from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    TurnHandlingOptions,
    cli,
    llm,
    tokenize,
    tts,
)
from livekit.plugins import silero

from .runtime import AgentConfig, build_llm, build_local_turn_detector
from .voice_models import DEFAULT_VOICE, NemotronSTT, VibeVoiceTTS

load_dotenv(Path(__file__).parents[2] / ".env")


def voice_runtime_executable() -> Path:
    configured = os.environ.get("MARVI_VOICE_RUNTIME")
    if configured:
        return Path(configured)
    suffix = ".exe" if os.name == "nt" else ""
    return Path(__file__).parents[3] / "voice-runtime" / "target" / "release" / f"marvi-voice-runtime{suffix}"


class MarviVoiceAgent(Agent):
    """Voice-only persona with an explicit local transcript wake gate."""

    def __init__(self, *, wake_word: str = "marvi", wake_timeout: float = 45.0) -> None:
        super().__init__(
            instructions=(
                "You are Marvi, a concise voice-first personal assistant. Speak naturally in short "
                "sentences. Never use Markdown, code fences, headings, or visual formatting. "
                "The user can interrupt you at any time."
            )
        )
        self._wake_word = wake_word.casefold()
        self._wake_timeout = wake_timeout
        self._armed_until = 0.0
        self._turn_allowed = False

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        text = " ".join(str(part) for part in new_message.content).casefold()
        now = time.monotonic()
        self._turn_allowed = self._wake_word in text or now < self._armed_until
        if self._turn_allowed:
            self._armed_until = now + self._wake_timeout

    def llm_node(self, chat_ctx: llm.ChatContext, tools: list[llm.Tool], model_settings: Any):
        if not self._turn_allowed:
            return None
        return super().llm_node(chat_ctx, tools, model_settings)


def build_session() -> AgentSession:
    local_tts = VibeVoiceTTS(voice=os.environ.get("MARVI_TTS_VOICE", DEFAULT_VOICE))
    streaming_tts = tts.StreamAdapter(
        tts=local_tts,
        sentence_tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=12),
    )
    return AgentSession(
        stt=NemotronSTT(
            executable=voice_runtime_executable(),
            language=os.environ.get("MARVI_STT_LANGUAGE", "tr-TR"),
        ),
        vad=silero.VAD.load(),
        llm=build_llm(AgentConfig.from_env()),
        tts=streaming_tts,
        turn_handling=TurnHandlingOptions(
            turn_detection=build_local_turn_detector(),
            endpointing={"mode": "dynamic", "min_delay": 0.25, "max_delay": 2.0},
            interruption={
                "enabled": True,
                "mode": "adaptive",
                "min_duration": 0.25,
                "false_interruption_timeout": 1.2,
                "resume_false_interruption": True,
            },
        ),
    )


server = AgentServer()


@server.rtc_session()
async def marvi_session(ctx: JobContext) -> None:
    session = build_session()
    await session.start(agent=MarviVoiceAgent(), room=ctx.room)


def main() -> None:
    cli.run_app(server)


if __name__ == "__main__":
    main()
