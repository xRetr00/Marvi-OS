import time

import pytest
from livekit.agents import llm

from marvi_agent.session import MarviVoiceAgent


@pytest.mark.asyncio
async def test_wake_word_arms_follow_up_turns() -> None:
    agent = MarviVoiceAgent(wake_timeout=30)
    message = llm.ChatMessage(role="user", content=["Marvi, turn on the light"])
    await agent.on_user_turn_completed(llm.ChatContext.empty(), message)
    assert agent._turn_allowed is True
    assert agent._armed_until > time.monotonic()


@pytest.mark.asyncio
async def test_background_speech_does_not_reach_llm() -> None:
    agent = MarviVoiceAgent()
    message = llm.ChatMessage(role="user", content=["this is background television"])
    await agent.on_user_turn_completed(llm.ChatContext.empty(), message)
    assert agent._turn_allowed is False
    assert agent.llm_node(llm.ChatContext.empty(), [], object()) is None

