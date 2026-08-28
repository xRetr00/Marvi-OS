import pytest
from livekit.agents import llm
from livekit.agents.voice import Agent

from marvi_agent.session import MarviVoiceAgent


@pytest.mark.asyncio
async def test_every_turn_reaches_the_model_once_the_session_is_open() -> None:
    """The gate that ate the conversation.

    `llm_node` used to return None unless the transcript contained "marvi",
    which meant: say her name, the session opens, ask a question -- and the
    question is discarded, silently, because the question did not also contain
    her name. Nothing was logged and nothing was said. It looked like the turn
    was never sent.

    A wake word starts a conversation. It is not a password on every sentence.
    """
    agent = MarviVoiceAgent()
    message = llm.ChatMessage(role="user", content=["what is the weather"])

    await agent.on_user_turn_completed(llm.ChatContext.empty(), message)

    # No gate left to consult, and no per-turn state to get wrong.
    assert not hasattr(agent, "_turn_allowed")
    assert not hasattr(agent, "_armed_until")
    assert MarviVoiceAgent.llm_node is Agent.llm_node, (
        "llm_node must not be overridden; overriding it is how turns disappeared"
    )


@pytest.mark.asyncio
async def test_a_heard_turn_is_logged(caplog) -> None:
    """So a turn that goes missing leaves a trace of having existed."""
    import logging

    agent = MarviVoiceAgent()
    message = llm.ChatMessage(role="user", content=["turn the light on"])

    with caplog.at_level(logging.INFO, logger="marvi.voice"):
        await agent.on_user_turn_completed(llm.ChatContext.empty(), message)

    assert any("turn the light on" in record.message for record in caplog.records)


def test_a_missing_speech_engine_is_reported(tmp_path, monkeypatch, caplog) -> None:
    """The failure that looked like nothing at all.

    An installed machine once had no recogniser at all and nothing said so.
    The wake word fired, the session listened, and no transcript was ever
    produced -- because the thing that turns audio into words was not there.

    The engine has changed twice since (a Rust sidecar, now a Parakeet ONNX
    export) and the failure has not: it is stated at the point it is decided,
    which is the only place that can tell "no speech" from "no engine".
    """
    import contextlib
    import logging

    from marvi_agent import session as session_module

    monkeypatch.setattr(session_module, "PARAKEET_ROOT", tmp_path / "absent", raising=True)

    # Building the rest of the session needs models this test has no business
    # downloading; the log line is what is under test, and it is emitted before
    # anything that can fail.
    with caplog.at_level(logging.ERROR, logger="marvi.voice"), contextlib.suppress(Exception):
        session_module.build_session()

    assert any("no speech recognition model" in record.message for record in caplog.records)


def test_a_present_engine_says_nothing(tmp_path, monkeypatch, caplog) -> None:
    import contextlib
    import logging

    from marvi_agent import session as session_module

    installed = tmp_path / "parakeet"
    installed.mkdir()
    (installed / "encoder-model.onnx").write_bytes(b"pretend model")
    monkeypatch.setattr(session_module, "PARAKEET_ROOT", installed, raising=True)

    with caplog.at_level(logging.ERROR, logger="marvi.voice"), contextlib.suppress(Exception):
        session_module.build_session()

    assert not any("missing" in record.message for record in caplog.records)


def test_the_session_and_its_model_loading_are_separable() -> None:
    """Loading the speech models must be something the caller can move.

    VibeVoice pulls in Qwen2.5-0.5B on first use. Loading it inline during
    `session.start` blocked the event loop for sixteen seconds, so nothing
    answered LiveKit's connect handshake and the Rust side killed the job:

        FFI Panic: timed out waiting for ReadyForRoomEventRequest

    Every voice session died there. The load is a separate callable so the
    entrypoint can run it in a thread, before the room connects.
    """
    import inspect

    from marvi_agent import session as session_module

    signature = inspect.signature(session_module.build_session)

    assert "tuple" in str(signature.return_annotation), (
        "build_session must hand back the warm-up separately from the session"
    )


def test_the_entrypoint_warms_off_the_event_loop() -> None:
    """In a thread, and before `session.start` -- both halves matter.

    In the thread but after start is still a blocked handshake; before start
    but on the loop is the original bug.
    """
    import inspect

    from marvi_agent import session as session_module

    source = inspect.getsource(session_module.marvi_session)

    assert "asyncio.to_thread(warm)" in source, "the load must not run on the event loop"
    assert source.index("to_thread(warm)") < source.index("session.start("), (
        "the models must be loaded before the room connect, not after"
    )


def test_nothing_mutes_the_session_input() -> None:
    """The bug that made speech look broken.

    The wake word lived in the Agent and gated `session.input`, so joining a
    room produced a session with its microphone switched off. VAD saw nothing,
    went `away`, and STT was never handed anything -- indistinguishable from
    speech recognition being broken, which is where we spent days looking.

    A wake word is a hands-free Join. It belongs on the side that can join,
    and a session that exists is a session that is listening.
    """
    import inspect

    from marvi_agent import session as session_module

    source = inspect.getsource(session_module)

    assert "set_audio_enabled" not in source, (
        "the session must never mute its own input; a wake word is not a gate"
    )
    assert "WakeGate" not in source


def test_the_voice_comes_from_the_gateway(monkeypatch) -> None:
    """Preferences must reach a process that cannot see them.

    The Agent's environment is fixed when the desktop spawns it, so choosing a
    voice wrote to something it never read and Marvi kept the old one.
    """
    import inspect

    from marvi_agent import session as session_module

    source = inspect.getsource(session_module.configured_voice)

    assert "/voices" in source, "the voice must be asked of the Gateway"
    assert "MARVI_TTS_VOICE" in source, "and the environment must remain a fallback"


def test_a_deleted_voice_falls_back_rather_than_failing(monkeypatch) -> None:
    """Reported missing by the Gateway; better a default voice than none."""
    from marvi_agent import session as session_module

    monkeypatch.setenv("MARVI_TTS_VOICE", "en-Fallback_man")

    class Gone:
        @staticmethod
        def json():
            return {"selected": "en-Deleted_woman", "missing": True}

    monkeypatch.setattr("httpx.get", lambda *a, **k: Gone())

    assert session_module.configured_voice() == "en-Fallback_man"


def test_the_persona_forbids_composing_a_memory_list() -> None:
    """The worst turn in the logs, as a rule she carries.

    Asked "uh about the memory", Marvi listed six memories in the third
    person -- "she works fully locally, uses model Llama 3.2 3B Instruct Q4
    from Ollama" -- and spoke for sixty-eight seconds. Two memories had been
    recalled for that turn, neither of them those, and nothing she said exists
    in the store. She had written a plausible memory list rather than reading
    one.
    """
    instructions = MarviVoiceAgent().instructions

    assert "only what recall gave you" in instructions
    assert "never compose a list of things that sound like memories" in instructions
