"""Bounded chat dictation adapter for Marvi's speech-recognition worker.

The renderer captures microphone frames; this adapter owns the sidecar process
and forwards only 16 kHz mono PCM16. It never calls an LLM and never stores
audio. A session is explicit and short-lived so abandoning Chat cannot leave a
GPU recognizer running forever.

It listens with the recogniser selected in Settings. It used to be Parakeet v3
whatever was chosen, so an install running Nemotron still had to keep 2.4 GB
of Parakeet for Chat alone. Kyutai runs in its own environment and has no
dictation path, so choosing it dictates with whichever of the other two is
installed.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import paths
from .doctor import find_uv

MAX_CHUNK_BYTES = 128 * 1024

#: What to actually send, which is not the same as what is allowed.
#:
#: `MAX_CHUNK_BYTES` is what this module will accept from a caller. Half a
#: second of 16 kHz mono is what it sends, which keeps the partials arriving
#: at a readable pace.
#:
#: This used to be written down as a limit of the `nemotron-3.5` runtime --
#: that it died on 64 KiB pieces and survived 16,000-byte ones. It does not.
#: Both sizes decode the same audio into the same number of 160 ms blocks and
#: produce the same stderr, and the deaths were the stderr pipe filling rather
#: than the chunk size; see `WORKER_STDERR_LINES`. Re-measured with the pipe
#: drained: 30 s of speech flushes in 0.0 s at 64 KiB as well as at 16,000.
CHUNK_BYTES = 16_000
SESSION_TTL_SECONDS = 120.0

#: How many lines of the worker's stderr to keep for the error message.
#:
#: The worker's stderr has to be read while it runs, and this is why: a Windows
#: anonymous pipe holds 4 KiB by default, and parakeet.cpp narrates every CUDA
#: graph compute to stderr -- roughly 500 bytes a second of
#: "ggml_backend_cuda_graph_compute: CUDA graph warmup complete". Nothing read
#: it, so once a session passed about 4 KiB the pipe filled, the worker blocked
#: inside its own write to stderr, and it could no longer answer on stdout. The
#: Gateway saw a recogniser that had stopped responding and reported
#: "speech runtime closed: ggml_cuda_init: ..." -- which is not a crash message
#: at all, only the top of the stderr that had been backing up since startup.
#:
#: Measured on this host (RTX 3060), driving the worker with real speech:
#:
#:      6 s of audio   3,068 bytes of stderr   flush returns
#:     12 s of audio   5,639 bytes of stderr   worker blocks at 8.5 s in
#:
#: The same 12 s clip finalises in 0.1 s with stderr pointed at a file, and 30 s
#: finalises in 0.0 s with the pipe drained, so neither the streaming wrapper
#: nor `parakeet.dll` has a length limit -- the pipe did.
#:
#: Bounded because this is only ever read to explain a failure, and the last
#: lines are the ones that say what went wrong.
WORKER_STDERR_LINES = 50


class DictationError(RuntimeError):
    pass


REPO_ROOT = Path(__file__).resolve().parents[4]


def worker_command() -> list[str]:
    uv = find_uv()
    if not uv:
        return []
    return [
        uv,
        "run",
        "--project",
        str(REPO_ROOT / "services" / "agent"),
        "python",
        "-m",
        "marvi_agent.dictation_worker",
    ]


def _installed(engine: str) -> bool:
    if engine == "nemotron-3.5":
        return (
            paths.root() / "runtimes/parakeet-cpp/lib/parakeet.dll"
        ).is_file() and (
            paths.models_dir() / "stt/nemotron-3.5-asr-streaming-0.6b"
            / "nemotron-3.5-asr-streaming-0.6b-f16.gguf"
        ).is_file()
    return (paths.models_dir() / "stt/parakeet-tdt-0.6b-v3-onnx/encoder-model.onnx").is_file()


def engine() -> str:
    """The recogniser to dictate with: the selected one when it can, else
    whichever dictation-capable one is installed, else ""."""
    selected = os.environ.get("MARVI_STT_ENGINE", "").strip().lower() or "parakeet-tdt"
    for candidate in (selected, "nemotron-3.5", "parakeet-tdt"):
        if candidate in ("nemotron-3.5", "parakeet-tdt") and _installed(candidate):
            return candidate
    return ""


class _Stderr:
    """The worker's stderr, read as it arrives. See `WORKER_STDERR_LINES`.

    Reading it is not optional, and it is read on a thread because the only
    other reader is the one waiting on stdout for the worker's next answer.
    """

    def __init__(self, stream: Any) -> None:
        self.lines: deque[str] = deque(maxlen=WORKER_STDERR_LINES)
        self.ended = threading.Event()
        threading.Thread(target=self._drain, args=(stream,), daemon=True).start()

    def _drain(self, stream: Any) -> None:
        with contextlib.suppress(Exception):
            for line in iter(stream.readline, ""):
                self.lines.append(line)
        self.ended.set()

    def text(self, patience: float = 0.5) -> str:
        """What the worker said before it stopped.

        A worker that has died closes its stderr, so the wait is usually over
        the moment it is asked for; the bound is for one that is only wedged,
        where the last words already read are the ones worth reporting.
        """
        self.ended.wait(patience)
        return "".join(self.lines)


@dataclass
class _Session:
    process: Any
    touched: float
    errors: _Stderr | None


class DictationManager:
    def __init__(self, popen: Callable[..., Any] = subprocess.Popen) -> None:
        self._popen = popen
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def available(self) -> bool:
        return bool(worker_command()) and bool(engine())

    def start(self, language: str = "en-US") -> str:
        with self._lock:
            self._expire()
            if not self.available():
                raise DictationError("the installed Marvi speech-to-text runtime is unavailable")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = self._popen(
                [*worker_command(), language, engine()],
                cwd=REPO_ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                creationflags=flags,
            )
            errors = _Stderr(process.stderr) if process.stderr is not None else None
            ready = self._read(process, errors)
            if not ready.get("ok") or ready.get("kind") != "ready":
                self._terminate(process)
                raise DictationError(str(ready.get("error") or "speech runtime failed to start"))
            identifier = uuid4().hex
            self._sessions[identifier] = _Session(process, time.monotonic(), errors)
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
            response = self._send(
                session.process, {"op": "audio", "pcm16": pcm16}, session.errors
            )
            session.touched = time.monotonic()
            return response

    def stop(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session is None:
                raise DictationError("dictation session is no longer active")
            try:
                return self._send(session.process, {"op": "flush"}, session.errors)
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
    def _send(
        process: Any, payload: dict[str, str], errors: _Stderr | None = None
    ) -> dict[str, Any]:
        if process.poll() is not None or process.stdin is None:
            raise DictationError("speech runtime exited")
        process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        process.stdin.flush()
        response = DictationManager._read(process, errors)
        if not response.get("ok"):
            raise DictationError(str(response.get("error") or "speech recognition failed"))
        return response

    @staticmethod
    def _read(process: Any, errors: _Stderr | None = None) -> dict[str, Any]:
        line = process.stdout.readline() if process.stdout is not None else ""
        if not line:
            # Taken from what the drain thread has already read. Calling
            # `process.stderr.read()` here blocks until the worker's stderr
            # closes, which a worker that is merely stuck never does.
            detail = errors.text() if errors is not None else ""
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
