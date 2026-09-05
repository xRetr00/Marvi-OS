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


def test_a_barge_in_does_not_make_the_next_reply_reload_the_model(monkeypatch) -> None:
    """Interrupting Marvi cost fifty seconds of silence.

    `DRAIN_TIMEOUT` was one second, matched to `_STOP_GRACE` on the reasoning
    that a longer drain would be wasted. But an abandoned reply has most of a
    sentence left in it -- seconds of work at the ~1.8x this engine runs at --
    so one second killed the sidecar on essentially every barge-in, and a
    killed sidecar reloads: 37.7s to 43.9s for CuteTTS. The log has it in the
    very next reply:

        00:56:05  cutetts-distill did not finish after an interruption
        00:57:04  tts: 10.1s of audio in 50.4s (0.20x real time;
                  engine 0.20x, 0.0s waiting for the model)

    Both halves are off the reply path now: the drain gets a budget that fits
    a real sentence, and if the process does have to go, its replacement loads
    while the person is speaking rather than while Marvi is trying to answer.
    """
    from marvi_agent.voice_models import _SidecarEngine

    # Long enough for an abandoned sentence to finish. The failure was a
    # number too small to ever succeed.
    assert _SidecarEngine.DRAIN_TIMEOUT >= 10.0


def test_recovery_runs_off_the_thread_that_noticed_the_interruption() -> None:
    import threading

    from marvi_agent.voice_models import _SidecarEngine

    made = _SidecarEngine.__new__(_SidecarEngine)
    made.engine = "test-engine"
    made._recovering = None
    made._recovering_lock = threading.Lock()
    started = threading.Event()
    release = threading.Event()
    ran_on: list[int] = []

    def slow_drain() -> bool:
        ran_on.append(threading.get_ident())
        started.set()
        release.wait(5)
        return True

    made._drain = slow_drain  # type: ignore[method-assign]

    here = threading.get_ident()
    made._recover()
    assert started.wait(5), "recovery never started"
    # The caller is already back: the interruption path does not wait for it.
    assert ran_on and ran_on[0] != here

    release.set()
    made._settled()
    # And the next reply does wait, so it never finds a half-drained pipe.
    assert made._recovering is not None and not made._recovering.is_alive()


def test_a_cloned_voice_reaches_the_sidecar(tmp_path, monkeypatch) -> None:
    """The clone was thrown away before the engine ever asked for it.

    `offered` is the *catalog* -- the voices that ship with the engine -- and a
    cloned voice is by definition not in it, so
    `voice if voice in offered else default_voice` silently swapped every clone
    for the stock voice. Selecting it in Settings looked like it worked, the
    WAV was on disk, the sidecar would have used it, and Marvi answered in the
    bundled voice with nothing anywhere saying why.
    """
    from marvi_agent import voice_models

    monkeypatch.setattr(voice_models, "APP_DATA", tmp_path)
    engine = "voxtream2"
    recording = tmp_path / "voices" / engine / "marvi-short.wav"
    recording.parent.mkdir(parents=True, exist_ok=True)
    recording.write_bytes(b"RIFF....WAVE")

    assert voice_models.cloned_voice(engine, "marvi-short") == recording
    assert voice_models.cloned_voice(engine, "never-recorded") is None
    # A blank name is not a lookup; it is the absence of one.
    assert voice_models.cloned_voice(engine, "") is None


def test_a_clone_survives_the_whole_way_to_the_sidecar(tmp_path, monkeypatch) -> None:
    """The test above checked the ingredient and missed the meal.

    `cloned_voice` was correct and asserted; the substitution happened in
    `_SidecarEngine.shared`, which never consulted it. So the clone was gone
    before the engine that had been fixed to accept it was ever built, and the
    log read as a clean success:

        tts: the Gateway chose voxtream2/'marvi-short'
        tts: voxtream2 speaking as 'english-female' (a built-in voice)

    This asserts the name that comes out the far end, which is the only thing
    the user can hear.
    """
    from marvi_agent import voice_models

    monkeypatch.setattr(voice_models, "APP_DATA", tmp_path)
    engine = "voxtream2"
    recording = tmp_path / "voices" / engine / "marvi-short.wav"
    recording.parent.mkdir(parents=True, exist_ok=True)
    recording.write_bytes(b"RIFF....WAVE")

    assert voice_models.usable_voice(engine, "marvi-short") == "marvi-short"

    got: list[str] = []
    monkeypatch.setattr(voice_models._SidecarEngine, "__init__",
                        lambda self, engine, voice: got.append(voice))
    monkeypatch.setattr(voice_models.sidecars, "track", lambda _engine: None)
    monkeypatch.setattr(voice_models, "_SIDECARS", {})

    voice_models._SidecarEngine.shared(engine, "marvi-short")
    assert got == ["marvi-short"], f"the clone became {got}"


def test_a_voice_that_is_neither_still_falls_back(tmp_path, monkeypatch) -> None:
    # The fallback is right for a name that names nothing: an engine cannot
    # speak in a voice that does not exist. It was only ever wrong for clones.
    from marvi_agent import voice_models

    monkeypatch.setattr(voice_models, "APP_DATA", tmp_path)
    assert voice_models.cloned_voice("voxtream2", "typo-here") is None
