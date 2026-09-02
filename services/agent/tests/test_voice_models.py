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


def test_cute_uses_the_reference_voice_from_its_own_catalog() -> None:
    from marvi_agent import voice_models
    from marvi_agent.voice_models import SidecarTTS, build_tts

    voice_models._SIDECARS.clear()

    engine = build_tts("cutetts-distill", "cute-default")
    current = build_tts("cutetts-distill", "cute-reference")

    assert isinstance(engine, SidecarTTS)
    assert engine._engine.voice == "cute-reference"
    assert current._engine is engine._engine


def test_removed_ctc_engine_falls_back_to_kokoro() -> None:
    from marvi_agent.voice_models import KokoroTTS, build_tts

    assert isinstance(build_tts("ctc-tts-f", "ctc-f"), KokoroTTS)


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


def test_sidecar_launch_does_not_inherit_the_agent_virtualenv(monkeypatch) -> None:
    import io
    import json

    from marvi_agent import voice_models

    class Process:
        stdin = io.StringIO()
        stdout = io.StringIO(json.dumps({"event": "ready", "sample_rate": 24000}) + "\n")

        def poll(self):
            return None

    captured = {}
    monkeypatch.setenv("VIRTUAL_ENV", "agent-environment")
    monkeypatch.setattr(voice_models.shutil, "which", lambda name: "uv")
    monkeypatch.setattr(
        voice_models.subprocess,
        "Popen",
        lambda command, **options: captured.update(options) or Process(),
    )

    voice_models._SidecarEngine("voxtream2", "english-male")._start()

    assert "VIRTUAL_ENV" not in captured["env"]


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
    engine = voice_models._SidecarEngine("voxtream2", "english-female")
    engine._process = Process()

    engine.close()

    assert calls[0][0] == ["taskkill", "/PID", "4321", "/T", "/F"]
    assert engine._process is None


def test_switching_engine_stops_the_one_it_replaces() -> None:
    """A sidecar is a live process holding a model in VRAM. Switching engine
    three times left three of them resident, and on a 12 GB card the third has
    nowhere to go -- nothing reclaimed them, because a key the cache no longer
    looks anything up under is a key nothing ever visits again."""
    from marvi_agent import voice_models
    from marvi_agent.voice_models import build_tts

    voice_models._SIDECARS.clear()
    closed: list[str] = []

    first = build_tts("cutetts-distill", "cute-reference")
    assert hasattr(first, "_engine")
    first._engine.close = lambda: closed.append("cutetts-distill")  # type: ignore[method-assign]

    build_tts("voxtream2", "")

    assert closed == ["cutetts-distill"], "the replaced engine was left running"
    assert len(voice_models._SIDECARS) == 1, "more than one engine stayed warm"


def test_asking_for_the_same_engine_twice_keeps_it_warm() -> None:
    """Eviction must not evict the thing being asked for: reloading a model on
    every call would be worse than leaving two resident."""
    from marvi_agent import voice_models
    from marvi_agent.voice_models import build_tts

    voice_models._SIDECARS.clear()
    first = build_tts("cutetts-distill", "cute-reference")
    again = build_tts("cutetts-distill", "cute-reference")

    assert first._engine is again._engine


def test_a_warm_recogniser_for_another_model_is_not_reused(monkeypatch) -> None:
    """`warmed.get("stt") or ParakeetSTT()` took whatever had been prewarmed,
    so changing the recogniser in Settings left the old one loaded and the
    setting visibly did nothing. The TTS path already compared engines before
    reusing; this did not, because until there was a choice there was nothing
    to compare."""
    from marvi_agent import session as session_module

    released: list[str] = []

    class Warm:
        model = "parakeet-tdt-0.6b-v2"

        def release(self) -> None:
            released.append(self.model)

    from pathlib import Path

    import marvi_agent.parakeet_stt as stt_module

    monkeypatch.setattr(
        session_module,
        "build_stt",
        lambda: type("Fresh", (), {"model": "parakeet-tdt-0.6b-v3"})(),
    )
    monkeypatch.setattr(stt_module, "chosen_model", lambda: Path("parakeet-tdt-0.6b-v3-onnx"))
    monkeypatch.setattr(stt_module, "chosen_engine", lambda: "parakeet-tdt")
    warmed: dict = {"stt": Warm(), "stt_model": "parakeet-tdt-0.6b-v2"}

    listener = session_module._recogniser(warmed)

    assert listener.model == "parakeet-tdt-0.6b-v3"
    assert released == ["parakeet-tdt-0.6b-v2"], "the replaced recogniser kept its device memory"
    assert "stt" not in warmed


def test_the_warm_recogniser_is_reused_when_it_is_the_selected_one(monkeypatch) -> None:
    """Rebuilding ONNX sessions on every call is seconds, felt as Marvi not
    hearing the opening sentence."""
    from pathlib import Path

    import marvi_agent.parakeet_stt as stt_module
    from marvi_agent import session as session_module

    class Warm:
        model = "parakeet-tdt-0.6b-v3"

        def release(self) -> None:
            raise AssertionError("released the recogniser it was asked for")

    monkeypatch.setattr(stt_module, "chosen_model", lambda: Path("parakeet-tdt-0.6b-v3-onnx"))
    monkeypatch.setattr(stt_module, "chosen_engine", lambda: "parakeet-tdt")
    warm = Warm()

    assert (
        session_module._recogniser({"stt": warm, "stt_model": "parakeet-tdt-0.6b-v3"}) is warm
    )
