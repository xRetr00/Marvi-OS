"""What Nemotron writes into the transcript that nobody said.

The model is multilingual and marks what it decided it was listening to, in
band, as text -- so the tag reaches the log, the chat transcript, the prompt
and memory verbatim:

    stt: Yes, I was telling you you said something weird. <en-US> What was it? <en-US>

Twenty-eight of them in one afternoon of real turns.
"""

from __future__ import annotations

import numpy as np
import pytest

from marvi_agent import nemotron_stt


def stream(monkeypatch) -> nemotron_stt.NemotronStream:
    made = nemotron_stt.NemotronStream.__new__(nemotron_stt.NemotronStream)
    made._nemotron = None
    made._stream = None
    made._said = ""
    made._spoke_at = 0.0
    made._transcribing = True
    made._pending = np.zeros(0, dtype=np.float32)
    made._event_ch = _Channel()
    return made


class _Channel:
    def __init__(self) -> None:
        self.sent: list[tuple[object, str]] = []

    def send_nowait(self, event) -> None:
        self.sent.append((event.type, event.alternatives[0].text))


def test_the_language_tag_never_reaches_the_transcript(monkeypatch) -> None:
    made = stream(monkeypatch)
    for piece in ("Yes, I was telling you you said something weird.", " <en-US>", " What was it?", " <en-US>"):
        made._heard({"text": piece})

    assert made.transcript() == "Yes, I was telling you you said something weird. What was it?"


@pytest.mark.parametrize("tag", ["<en>", "<en-US>", "<fr-FR>", "<zh-Hans>"])
def test_every_locale_shape_is_removed(tag: str, monkeypatch) -> None:
    # The model is multilingual; English is not the only tag it can write.
    made = stream(monkeypatch)
    made._heard({"text": f"bonjour {tag} ca va"})
    assert tag not in made.transcript()
    assert made.transcript() == "bonjour ca va"


def test_ordinary_words_are_left_alone(monkeypatch) -> None:
    # This only removes what the model added. A transcript is the user's text.
    made = stream(monkeypatch)
    made._heard({"text": "is 3 < 5 and a > b"})
    assert made.transcript() == "is 3 < 5 and a > b"


def test_a_bare_space_is_still_a_word_boundary(monkeypatch) -> None:
    """The same accumulator bug the Kyutai adapter had.

    Stripping the whole transcript after every piece eats a piece that is only
    a space, and the next word lands against the last one -- one afternoon of
    "apretty", "thespeech" and "outsearch" on the other recogniser.
    """
    made = stream(monkeypatch)
    for piece in ("that's", " ", "a", " pretty"):
        made._heard({"text": piece})

    assert made.transcript() == "that's a pretty"


def test_the_interims_are_clean_too(monkeypatch) -> None:
    # Not only the final: the interim transcripts are what the Voice page
    # draws while somebody is still talking, and what the memory prefetch
    # searches on.
    made = stream(monkeypatch)
    made._heard({"text": "hello there <en-US>"})

    assert [text for _kind, text in made._event_ch.sent] == ["hello there"]
