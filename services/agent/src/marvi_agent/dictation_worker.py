"""JSON-lines adapter for short Chat dictation sessions.

`python -m marvi_agent.dictation_worker <language> <engine>`. The Gateway picks
the engine -- the recogniser selected in Settings when it can dictate -- so
Chat hears through the same model as Voice.
"""

from __future__ import annotations

import base64
import json
import sys
from typing import Any

import numpy as np


class ParakeetDictation:
    def __init__(self, asr: Any | None = None) -> None:
        if asr is None:
            from .parakeet_stt import ParakeetSTT

            asr = ParakeetSTT()._build()
        self.asr = asr
        self.pending = np.zeros(0, dtype=np.float32)
        self.transcript = ""
        self.first = True

    def audio(self, pcm16: bytes) -> str:
        samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32767.0
        self.pending = np.concatenate([self.pending, samples])
        wanted = self.asr._initial_samples_needed if self.first else self.asr.chunk_samples
        while self.pending.size >= wanted:
            block, self.pending = self.pending[:wanted], self.pending[wanted:]
            self.first = False
            self.asr.process_chunk(block, False)
            self._read_full_text()
            wanted = self.asr.chunk_samples
        return self.transcript

    def flush(self) -> str:
        self.asr.process_chunk(self.pending, True)
        self._read_full_text()
        result = self.transcript.strip()
        if hasattr(self.asr, "reset"):
            self.asr.reset()
        self.pending = np.zeros(0, dtype=np.float32)
        self.transcript = ""
        self.first = True
        return result

    def _read_full_text(self) -> None:
        """The decoder owns word boundaries; chunk deltas do not."""
        text = str(self.asr.get_full_text()).strip()
        if text:
            self.transcript = text


class NemotronDictation:
    """Nemotron through parakeet.cpp: 160 ms blocks in, text pieces out.

    The same feeding as `NemotronStream`, without LiveKit around it. The
    library returns only what each feed decoded, so the transcript is
    accumulated here and its language tags stripped where it is read.
    """

    def __init__(self, library: Any | None = None, language: str = "en") -> None:
        from .nemotron_stt import FEED_SAMPLES, LIBRARY, MODEL_FILE, MODEL_ROOT, _Library

        self.library = library or _Library(LIBRARY, MODEL_ROOT / MODEL_FILE, language)
        self.feed_samples = FEED_SAMPLES
        self.stream: Any = None
        self.said = ""
        self.pending = np.zeros(0, dtype=np.float32)

    def audio(self, pcm16: bytes) -> str:
        samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32_768.0
        self.pending = np.concatenate([self.pending, samples])
        if self.stream is None:
            self.stream = self.library.begin()
        while self.pending.size >= self.feed_samples:
            block, self.pending = (
                self.pending[: self.feed_samples],
                self.pending[self.feed_samples :],
            )
            self.said += str(self.library.feed(self.stream, block).get("text") or "")
        return self.transcript()

    def flush(self) -> str:
        if self.stream is not None:
            try:
                if self.pending.size:
                    self.said += str(self.library.feed(self.stream, self.pending).get("text") or "")
                self.said += str(self.library.finish(self.stream).get("text") or "")
            finally:
                self.library.end(self.stream)
        result = self.transcript()
        self.stream, self.said = None, ""
        self.pending = np.zeros(0, dtype=np.float32)
        return result

    def transcript(self) -> str:
        from .nemotron_stt import LANGUAGE_TAG

        return LANGUAGE_TAG.sub(" ", self.said).strip()


def respond(body: dict[str, Any]) -> str:
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False)


def recognizer_for(engine: str, language: str) -> Any:
    if engine == "nemotron-3.5":
        return NemotronDictation(language=(language or "en")[:2].lower())
    return ParakeetDictation()


def main() -> None:
    language = sys.argv[1] if len(sys.argv) > 1 else "en-US"
    engine = sys.argv[2] if len(sys.argv) > 2 else "parakeet-tdt"
    try:
        recognizer = recognizer_for(engine, language)
    except Exception as exc:
        print(respond({"ok": False, "error": f"{engine} could not start: {exc}"}), flush=True)
        return
    print(respond({"ok": True, "kind": "ready", "text": ""}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            operation = request.get("op")
            if operation == "audio":
                pcm = base64.b64decode(request.get("pcm16", ""), validate=True)
                result = {"ok": True, "kind": "partial", "text": recognizer.audio(pcm)}
            elif operation == "flush":
                result = {"ok": True, "kind": "final", "text": recognizer.flush()}
            else:
                result = {"ok": False, "error": "unknown dictation operation"}
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        print(respond(result), flush=True)


if __name__ == "__main__":
    main()
