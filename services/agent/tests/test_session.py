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



def test_a_missing_speech_engine_is_reported(tmp_path, monkeypatch, caplog) -> None:
    """The failure that looked like nothing at all.

    The engine is Rust and the toolchain Marvi provisions is uv and Node, so
    an installed machine had no STT binary and nothing said so. The wake word
    fired, the session listened, and no transcript was ever produced -- because
    the thing that turns audio into words was not there.

    It is now stated at the point it is decided, which is the only place that
    can tell the difference between "no speech" and "no engine".
    """
    import logging

    from marvi_agent import session as session_module

    monkeypatch.setenv("MARVI_VOICE_RUNTIME", str(tmp_path / "absent.exe"))

    with caplog.at_level(logging.ERROR, logger="marvi.voice"):
        try:
            session_module.build_session()
        except Exception:
            # Building the rest of the session needs models this test has no
            # business downloading. The log line is what is under test.
            pass

    assert any("speech-to-text engine is missing" in record.message for record in caplog.records)


def test_a_present_engine_says_nothing(tmp_path, monkeypatch, caplog) -> None:
    import logging

    from marvi_agent import session as session_module

    engine = tmp_path / "marvi-voice-runtime.exe"
    engine.write_bytes(b"pretend engine")
    monkeypatch.setenv("MARVI_VOICE_RUNTIME", str(engine))

    with caplog.at_level(logging.ERROR, logger="marvi.voice"):
        try:
            session_module.build_session()
        except Exception:
            pass

    assert not any("missing" in record.message for record in caplog.records)
