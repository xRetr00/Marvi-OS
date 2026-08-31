def test_a_clause_is_spoken_before_the_sentence_is_finished() -> None:
    """The difference between answering and pausing to compose.

    LiveKit's StreamAdapter batches into sentences of at least twelve
    characters, so a short reply waited for words that were never coming and
    every reply paid that delay before its first sound. The engine takes a
    whole utterance rather than tokens, so some batching is unavoidable —
    owning it is what lets the first clause be spoken as soon as it is one.
    """
    from marvi_agent.voice_models import _next_clause

    clause, rest = _next_clause("The light is on. Anything else?")

    assert clause == "The light is on."
    assert rest == " Anything else?"


def test_an_unfinished_clause_waits() -> None:
    """Speaking half a phrase is worse than a moment's wait."""
    from marvi_agent.voice_models import _next_clause

    assert _next_clause("The light is") == ("", "The light is")


def test_a_fragment_too_short_to_speak_alone_is_held() -> None:
    """ "Yes" then "it is" as two utterances sounds like two answers."""
    from marvi_agent.voice_models import _next_clause

    assert _next_clause("Hi.")[0] == ""


def test_the_session_does_not_wrap_the_tts() -> None:
    """A native streaming TTS through StreamAdapter is batching twice."""
    import inspect

    from marvi_agent import session

    # The construction, not the word: the comment above it explains why the
    # adapter is gone and would match a naive search.
    assert "StreamAdapter(" not in inspect.getsource(session.build_session)


def test_a_tool_call_written_as_text_is_not_spoken() -> None:
    """The model wrote the call instead of making it, and Marvi read it aloud.

    From a real session: thirty-nine seconds of audio for one reply, most of it
    tag names and file contents. The tool had not run either -- that is a
    separate fault -- but nothing should ever put markup through the voice.
    """
    from marvi_agent.voice_models import _speakable

    said, markup = _speakable('The file is saved at shreef.txt. <invoke name="file_read">')

    assert said == "The file is saved at shreef.txt."
    assert markup is True


def test_ordinary_speech_passes_through_untouched() -> None:
    from marvi_agent.voice_models import _speakable

    assert _speakable("The light is on.") == ("The light is on.", False)
    # A comparison is not a tag.
    assert _speakable("Three is < five.") == ("Three is < five.", False)


def test_kokoro_remains_the_default_tts() -> None:
    from marvi_agent.voice_models import KokoroTTS, build_tts

    assert isinstance(build_tts(), KokoroTTS)


def test_optional_tts_uses_the_isolated_runtime() -> None:
    from marvi_agent.voice_models import SidecarTTS, build_tts

    engine = build_tts("voxtream2", "english-male")

    assert isinstance(engine, SidecarTTS)
    assert engine.engine_id == "voxtream2"
    assert engine._engine.voice == "english-male"


def test_a_voice_from_another_engine_falls_back_locally() -> None:
    from marvi_agent.voice_models import SidecarTTS, build_tts

    engine = build_tts("ctc-tts-f", "am_michael")

    assert isinstance(engine, SidecarTTS)
    assert engine._engine.voice == "ctc-f"


def test_sidecar_protocol_streams_pcm_and_sends_the_selected_voice() -> None:
    import base64
    import io
    import json
    import threading

    from marvi_agent.voice_models import _SidecarEngine

    pcm = b"\x01\x02" * 40

    class Process:
        def __init__(self) -> None:
            self.stdin = io.StringIO()
            self.stdout = io.StringIO(
                json.dumps({"event": "chunk", "pcm": base64.b64encode(pcm).decode()})
                + "\n"
                + json.dumps({"event": "done"})
                + "\n"
            )

        def poll(self):
            return None

    engine = _SidecarEngine("voxtream2", "english-male")
    process = Process()
    engine._process = process

    assert list(engine.synthesize("Hello.", threading.Event())) == [pcm]
    request = json.loads(process.stdin.getvalue())
    assert request == {"text": "Hello.", "voice": "english-male"}


def test_sidecar_close_kills_the_windows_process_tree(monkeypatch) -> None:
    from marvi_agent import voice_models

    class Process:
        pid = 4321

        def poll(self):
            return None

        def wait(self, *, timeout):
            assert timeout == 5
            return 0

    calls = []
    monkeypatch.setattr(voice_models.os, "name", "nt")
    monkeypatch.setattr(
        voice_models.subprocess,
        "run",
        lambda command, **options: calls.append((command, options)),
    )
    engine = voice_models._SidecarEngine("ctc-tts-f", "ctc-f")
    engine._process = Process()

    engine.close()

    assert calls[0][0] == ["taskkill", "/PID", "4321", "/T", "/F"]
    assert engine._process is None
