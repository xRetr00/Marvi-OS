"""Standalone one-shot speech never needs a LiveKit participant."""

from __future__ import annotations

import threading

from marvi_gateway.announce import Announcer, _chunks, marker_path


class RecordingPlayer:
    def __init__(self) -> None:
        self.audio: list[tuple[bytes, int]] = []
        self.marker_seen = False

    def play(self, pcm, rate, cancelled):
        self.marker_seen = marker_path().is_file()
        self.audio.append((pcm, rate))
        return not cancelled.is_set()


def test_one_shot_synthesises_and_plays_without_a_room(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MARVI_HOME", str(tmp_path / "marvi"))
    player = RecordingPlayer()
    announcer = Announcer(player=player)
    monkeypatch.setattr(announcer, "synthesize", lambda text: (b"\x00\x00" * 2400, 24_000))

    result = announcer.speak("Welcome home.", purpose="proactive")

    assert result == {"played": True, "cancelled": False, "seconds": 0.1}
    assert player.audio == [(b"\x00\x00" * 2400, 24_000)]
    assert player.marker_seen is True
    assert marker_path().exists() is False


def test_model_assets_are_forced_under_marvis_removable_cache(monkeypatch, tmp_path) -> None:
    from huggingface_hub import constants as hf_constants

    monkeypatch.setenv("MARVI_HOME", str(tmp_path / "marvi"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "somewhere-else"))
    # Register restoration because Announcer intentionally updates an imported
    # Hugging Face constant when another dependency imported it first.
    monkeypatch.setattr(hf_constants, "HF_HUB_CACHE", hf_constants.HF_HUB_CACHE)

    class FakeModel:
        @classmethod
        def load_model(cls):
            return cls()

        def get_state_for_audio_prompt(self, _voice):
            return {}

    monkeypatch.setattr("pocket_tts.TTSModel", FakeModel)
    Announcer().prepare()

    assert __import__("os").environ["HF_HUB_CACHE"] == str(
        tmp_path / "marvi" / "models" / "pocket-tts" / "huggingface"
    )


def test_long_read_aloud_is_split_at_word_boundaries() -> None:
    parts = _chunks("one two three four", limit=8)
    assert parts == ["one two", "three", "four"]
    assert " ".join(parts) == "one two three four"


def test_an_oversized_token_is_still_bounded() -> None:
    assert _chunks("hi abcdefghijk", limit=5) == ["hi", "abcde", "fghij", "k"]


def test_stop_cancels_active_playback(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MARVI_HOME", str(tmp_path / "marvi"))
    started = threading.Event()

    class WaitingPlayer:
        def play(self, _pcm, _rate, cancelled):
            started.set()
            assert cancelled.wait(timeout=2)
            return False

    announcer = Announcer(player=WaitingPlayer())
    monkeypatch.setattr(announcer, "synthesize", lambda text: (b"\x00\x00" * 100, 24_000))
    result = {}
    worker = threading.Thread(target=lambda: result.update(announcer.speak("Keep reading.")))
    worker.start()
    assert started.wait(timeout=2)

    assert announcer.stop() is True
    worker.join(timeout=2)

    assert result["cancelled"] is True
    assert marker_path().exists() is False
