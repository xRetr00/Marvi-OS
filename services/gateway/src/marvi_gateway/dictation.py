"""Bounded chat dictation adapter for Marvi's native streaming STT sidecar.

The renderer captures microphone frames; this adapter owns the sidecar process
and forwards only 16 kHz mono PCM16. It never calls an LLM and never stores
audio. A session is explicit and short-lived so abandoning Chat cannot leave a
GPU recognizer running forever.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import paths

MAX_CHUNK_BYTES = 128 * 1024
SESSION_TTL_SECONDS = 120.0


class DictationError(RuntimeError):
    pass


def executable_path() -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return paths.runtime_dir() / "voice-runtime" / f"marvi-voice-runtime{suffix}"


def model_path() -> Path:
    return paths.models_dir() / "stt" / "nemotron-3.5" / "nemotron-3.5-asr-streaming-0.6b-onnx"


@dataclass
class _Session:
    process: Any
    touched: float


class DictationManager:
    def __init__(self, popen: Callable[..., Any] = subprocess.Popen) -> None:
        self._popen = popen
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def available(self) -> bool:
        return executable_path().is_file() and model_path().is_dir()

    def start(self, language: str = "en-US") -> str:
        with self._lock:
            self._expire()
            if not self.available():
                raise DictationError("the installed Marvi speech-to-text runtime is unavailable")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = self._popen(
                [str(executable_path()), str(model_path()), language],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                creationflags=flags,
            )
            ready = self._read(process)
            if not ready.get("ok") or ready.get("kind") != "ready":
                self._terminate(process)
                raise DictationError(str(ready.get("error") or "speech runtime failed to start"))
            identifier = uuid4().hex
            self._sessions[identifier] = _Session(process, time.monotonic())
            return identifier

    def audio(self, session_id: str, pcm16: str) -> dict[str, Any]:
        try:
            decoded = base64.b64decode(pcm16, validate=True)
        except (ValueError, TypeError) as exc:
            raise DictationError("dictation audio is not valid base64") from exc
        if not decoded or len(decoded) > MAX_CHUNK_BYTES or len(decoded) % 2:
            raise DictationError("dictation chunks must be even PCM16 data under 128 KiB")
        with self._lock:
            session = self._session(session_id)
            response = self._send(session.process, {"op": "audio", "pcm16": pcm16})
            session.touched = time.monotonic()
            return response

    def stop(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session is None:
                raise DictationError("dictation session is no longer active")
            try:
                return self._send(session.process, {"op": "flush"})
            finally:
                self._terminate(session.process)

    def cancel(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session is None:
                return False
            self._terminate(session.process)
            return True

    def close(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                self._terminate(session.process)
            self._sessions.clear()

    def _session(self, session_id: str) -> _Session:
        self._expire()
        session = self._sessions.get(session_id)
        if session is None:
            raise DictationError("dictation session is no longer active")
        return session

    def _expire(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, value in self._sessions.items()
            if now - value.touched > SESSION_TTL_SECONDS
        ]
        for key in expired:
            self._terminate(self._sessions.pop(key).process)

    @staticmethod
    def _send(process: Any, payload: dict[str, str]) -> dict[str, Any]:
        if process.poll() is not None or process.stdin is None:
            raise DictationError("speech runtime exited")
        process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        process.stdin.flush()
        response = DictationManager._read(process)
        if not response.get("ok"):
            raise DictationError(str(response.get("error") or "speech recognition failed"))
        return response

    @staticmethod
    def _read(process: Any) -> dict[str, Any]:
        line = process.stdout.readline() if process.stdout is not None else ""
        if not line:
            detail = process.stderr.read() if process.stderr is not None else ""
            raise DictationError(f"speech runtime closed: {detail}".strip())
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DictationError("speech runtime returned invalid data") from exc
        return response if isinstance(response, dict) else {}

    @staticmethod
    def _terminate(process: Any) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
