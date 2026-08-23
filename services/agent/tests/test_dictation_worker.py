from __future__ import annotations

import numpy as np

from marvi_agent.dictation_worker import ParakeetDictation


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
