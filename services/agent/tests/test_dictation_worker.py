from __future__ import annotations

import numpy as np

from marvi_agent.dictation_worker import NemotronDictation, ParakeetDictation, recognizer_for


class FakeAsr:
    _initial_samples_needed = 4
    chunk_samples = 4

    def __init__(self) -> None:
        self.calls = []
        self.reset_count = 0
        self.text = ""

    def process_chunk(self, block, last):
        self.calls.append((block.copy(), last))
        self.text = "hello" if not last else "hello world"
        return "ignored chunk delta"

    def get_full_text(self):
        return self.text

    def reset(self):
        self.reset_count += 1


def test_dictation_uses_parakeet_chunks_and_flushes_the_tail() -> None:
    asr = FakeAsr()
    recognizer = ParakeetDictation(asr)
    pcm = np.array([1, 2, 3, 4, 5, 6], dtype=np.int16).tobytes()

    assert recognizer.audio(pcm) == "hello"
    assert recognizer.flush() == "hello world"
    assert [last for _block, last in asr.calls] == [False, True]
    assert asr.calls[-1][0].size == 2
    assert asr.reset_count == 1


class FakeLibrary:
    """parakeet.cpp's shape: each feed returns only what it decoded."""

    def __init__(self) -> None:
        self.fed: list[int] = []
        self.ended = 0

    def begin(self):
        return 7

    def feed(self, stream, block):
        self.fed.append(block.size)
        return {"text": " hello" if len(self.fed) == 1 else " <en-US> there"}

    def finish(self, stream):
        return {"text": " world"}

    def end(self, stream):
        self.ended += 1


def test_nemotron_dictation_accumulates_pieces_and_strips_language_tags() -> None:
    library = FakeLibrary()
    recognizer = NemotronDictation(library)
    step = recognizer.feed_samples
    pcm = np.zeros(step + 10, dtype=np.int16).tobytes()

    assert recognizer.audio(pcm) == "hello"
    assert library.fed == [step], "only whole blocks are fed while listening"
    assert recognizer.flush() == "hello there world"
    assert library.fed == [step, 10], "the tail is fed at the end, not dropped"
    assert library.ended == 1
    assert recognizer.flush() == "", "a flush starts the next utterance clean"


def test_the_worker_listens_with_the_engine_it_was_given(monkeypatch) -> None:
    monkeypatch.setattr(NemotronDictation, "__init__", lambda self, **_k: None)
    assert isinstance(recognizer_for("nemotron-3.5", "en-US"), NemotronDictation)
