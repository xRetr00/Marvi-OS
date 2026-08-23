"""JSON-lines adapter for short Chat dictation sessions using Marvi's Parakeet STT."""

from __future__ import annotations

import base64
import json
import sys
from typing import Any

import numpy as np

from .parakeet_stt import ParakeetSTT


class ParakeetDictation:
    def __init__(self, asr: Any | None = None) -> None:
        self.asr = asr or ParakeetSTT()._build()
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


def respond(body: dict[str, Any]) -> str:
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False)


def main() -> None:
    recognizer = ParakeetDictation()
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
