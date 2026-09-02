"""Nemotron 3.5 Streaming, through parakeet.cpp's C ABI.

The second recogniser Marvi can be told to use, and the reason it is here is
one number. Measured on 2 September 2026 over 162 EdAcc clips, 2,158 reference
words:

    parakeet-tdt-0.6b-v2   WER 20.81%   RTF 0.055   first partial 2,910 ms
    nemotron-3.5           WER 24.79%   RTF 0.090   first partial 1,063 ms

Four points of word error for 1.8 seconds off the first word. That is not a
better recogniser; it is a different trade, and which one is right depends on
whether the person is dictating or talking. So it is offered rather than
promoted, and `parakeet-tdt` stays the default.

## Why it is a C ABI and not ONNX

parakeet.cpp ships official Windows CUDA binaries and f16 GGUFs, and there is
no ONNX export of this model. The library is loaded once per process and the
handle is shared, because the weights are the expensive part and a stream is
cheap -- the same shape `ParakeetSTT` uses for its ONNX sessions.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
from livekit.agents import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions, stt
from livekit.agents.types import NOT_GIVEN, NotGivenOr

from .parakeet_stt import APP_DATA, SAMPLE_RATE

log = logging.getLogger("marvi.voice")

#: The ABI this binding was written against. parakeet.cpp bumps it on breaking
#: changes, and a mismatched library is a crash rather than a wrong answer, so
#: it is refused up front with something a person can read.
ABI = 6

MODEL_ROOT = APP_DATA / "models/stt/nemotron-3.5-asr-streaming-0.6b"
MODEL_FILE = "nemotron-3.5-asr-streaming-0.6b-f16.gguf"

#: Where the official Windows CUDA build lands. Two directories: the library
#: itself and the CUDA runtime it needs on the DLL search path.
RUNTIME_ROOT = APP_DATA / "runtimes/parakeet-cpp"
LIBRARY = RUNTIME_ROOT / "lib/parakeet.dll"
CUDA_RUNTIME = RUNTIME_ROOT / "cudart"

#: How much audio to hand over at a time. The benchmark fed 160 ms and
#: measured a 1,063 ms first partial at that size; feeding larger blocks makes
#: the recogniser wait for them, which is the one thing this engine is chosen
#: for not doing.
FEED_SECONDS = 0.16
FEED_SAMPLES = int(FEED_SECONDS * SAMPLE_RATE)


class NemotronUnavailableError(RuntimeError):
    """The library or the weights are not installed. Said, not guessed at."""


def installed() -> bool:
    return LIBRARY.is_file() and (MODEL_ROOT / MODEL_FILE).is_file()


class _Library:
    """parakeet.cpp, loaded once. The weights are what cost; a stream is cheap."""

    def __init__(self, library: Path, model: Path, language: str = "en") -> None:
        if not library.is_file():
            raise NemotronUnavailableError(f"parakeet.cpp is not installed at {library}")
        if not model.is_file():
            raise NemotronUnavailableError(f"the Nemotron weights are not at {model}")
        if CUDA_RUNTIME.is_dir():
            os.add_dll_directory(str(CUDA_RUNTIME))
        os.add_dll_directory(str(library.parent))
        self._dll = ctypes.CDLL(str(library))
        self._bind()
        if self._dll.parakeet_capi_abi_version() != ABI:
            raise NemotronUnavailableError(
                f"parakeet.cpp ABI is v{self._dll.parakeet_capi_abi_version()}, "
                f"this build expects v{ABI}"
            )
        self.language = language.encode()
        self._context = self._dll.parakeet_capi_load(str(model).encode())
        if not self._context:
            raise NemotronUnavailableError("parakeet.cpp could not load the model")

    def _bind(self) -> None:
        dll = self._dll
        dll.parakeet_capi_abi_version.restype = ctypes.c_int
        dll.parakeet_capi_load.argtypes = [ctypes.c_char_p]
        dll.parakeet_capi_load.restype = ctypes.c_void_p
        dll.parakeet_capi_free.argtypes = [ctypes.c_void_p]
        dll.parakeet_capi_last_error.argtypes = [ctypes.c_void_p]
        dll.parakeet_capi_last_error.restype = ctypes.c_char_p
        dll.parakeet_capi_stream_begin_lang.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        dll.parakeet_capi_stream_begin_lang.restype = ctypes.c_void_p
        dll.parakeet_capi_stream_feed_json.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_int,
        ]
        dll.parakeet_capi_stream_feed_json.restype = ctypes.c_void_p
        dll.parakeet_capi_stream_finalize_json.argtypes = [ctypes.c_void_p]
        dll.parakeet_capi_stream_finalize_json.restype = ctypes.c_void_p
        dll.parakeet_capi_stream_free.argtypes = [ctypes.c_void_p]
        dll.parakeet_capi_free_string.argtypes = [ctypes.c_void_p]

    def begin(self) -> int:
        stream = self._dll.parakeet_capi_stream_begin_lang(self._context, self.language)
        if not stream:
            raise RuntimeError(self._said_wrong())
        return stream

    def feed(self, stream: int, block: np.ndarray) -> dict[str, Any]:
        buffer = (ctypes.c_float * block.size)(*block.tolist())
        return self._read(
            self._dll.parakeet_capi_stream_feed_json(stream, buffer, block.size)
        )

    def finish(self, stream: int) -> dict[str, Any]:
        return self._read(self._dll.parakeet_capi_stream_finalize_json(stream))

    def end(self, stream: int) -> None:
        with contextlib.suppress(Exception):
            self._dll.parakeet_capi_stream_free(stream)

    def _said_wrong(self) -> str:
        return self._dll.parakeet_capi_last_error(self._context).decode()

    def _read(self, pointer: int | None) -> dict[str, Any]:
        if not pointer:
            raise RuntimeError(self._said_wrong())
        try:
            return json.loads(ctypes.string_at(pointer).decode())
        finally:
            self._dll.parakeet_capi_free_string(pointer)

    def release(self) -> None:
        """Give the weights back. See `NemotronSTT.release`."""
        if getattr(self, "_context", None):
            with contextlib.suppress(Exception):
                self._dll.parakeet_capi_free(self._context)
            self._context = None


class NemotronSTT(stt.STT):
    """Streaming recognition through parakeet.cpp, one model shared by streams."""

    def __init__(self, *, model_dir: Path | None = None) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True, interim_results=True, offline_recognize=False
            )
        )
        self._model_dir = model_dir or MODEL_ROOT
        self._library: _Library | None = None
        self._streams: set[NemotronStream] = set()

    @property
    def model(self) -> str:
        return "nemotron-3.5-asr-streaming-0.6b"

    @property
    def provider(self) -> str:
        return "nvidia/parakeet.cpp"

    def prewarm(self) -> None:
        self._build()

    def _build(self) -> _Library:
        if self._library is not None:
            return self._library
        began = time.monotonic()
        self._library = _Library(LIBRARY, self._model_dir / MODEL_FILE)
        log.info("stt: nemotron ready in %.1fs", time.monotonic() - began)
        return self._library

    async def _recognize_impl(self, *args: Any, **kwargs: Any) -> stt.SpeechEvent:
        raise NotImplementedError("NemotronSTT is streaming-only")

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> NemotronStream:
        stream = NemotronStream(stt=self, conn_options=conn_options)
        self._streams.add(stream)
        return stream

    def set_transcribing(self, on: bool) -> None:
        for stream in tuple(self._streams):
            stream.set_transcribing(on)

    async def aclose(self) -> None:
        await asyncio.gather(*(stream.aclose() for stream in tuple(self._streams)))
        self._streams.clear()
        self.release()

    def release(self) -> None:
        """Hand the weights back to the card.

        The whole point of having a choice of recogniser is that only the
        chosen one is resident. A GGUF on a 12 GB card is not something to
        leave loaded because nothing asked for it again.
        """
        if self._library is not None:
            self._library.release()
            self._library = None


class NemotronStream(stt.RecognizeStream):
    """One utterance, fed in 160 ms blocks, flushed at the end."""

    #: Silence after speech before the utterance is called finished. The same
    #: as `ParakeetStream._SILENCE`, deliberately: turn-taking should not feel
    #: different because the recogniser was swapped.
    _SILENCE = 0.6

    def __init__(self, *, stt: NemotronSTT, conn_options: APIConnectOptions) -> None:
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=SAMPLE_RATE)
        self._nemotron = stt
        self._stream: int | None = None
        self._said = ""
        self._spoke_at = time.monotonic()
        self._transcribing = True
        self._pending = np.zeros(0, dtype=np.float32)

    def set_transcribing(self, on: bool) -> None:
        self._transcribing = on

    def _emit(self, kind: stt.SpeechEventType, text: str) -> None:
        self._event_ch.send_nowait(
            stt.SpeechEvent(
                type=kind, alternatives=[stt.SpeechData(language="en", text=text)]
            )
        )

    def _heard(self, update: dict[str, Any]) -> None:
        # parakeet.cpp returns the text decoded in *this* feed, so the
        # transcript is accumulated here. `ParakeetStream` re-reads the whole
        # utterance instead because its decoder offers one; this API does not.
        piece = str(update.get("text") or "")
        if not piece:
            return
        self._said = (self._said + piece).strip()
        self._spoke_at = time.monotonic()
        self._emit(stt.SpeechEventType.INTERIM_TRANSCRIPT, self._said)

    async def _settle(self, library: _Library) -> None:
        if self._stream is None:
            return
        stream, self._stream = self._stream, None
        with contextlib.suppress(Exception):
            self._heard(await asyncio.to_thread(library.finish, stream))
        library.end(stream)
        if self._said:
            self._emit(stt.SpeechEventType.FINAL_TRANSCRIPT, self._said)
        self._said = ""
        self._pending = np.zeros(0, dtype=np.float32)

    async def _run(self) -> None:
        library = await asyncio.to_thread(self._nemotron._build)
        try:
            async for item in self._input_ch:
                if isinstance(item, self._FlushSentinel):
                    await self._settle(library)
                    continue
                samples = np.frombuffer(bytes(item.data), dtype=np.int16)
                if not samples.size or not self._transcribing:
                    continue
                self._pending = np.concatenate(
                    [self._pending, samples.astype(np.float32) / 32_768.0]
                )
                if self._stream is None:
                    self._stream = await asyncio.to_thread(library.begin)
                while self._pending.size >= FEED_SAMPLES:
                    block = self._pending[:FEED_SAMPLES]
                    self._pending = self._pending[FEED_SAMPLES:]
                    self._heard(
                        await asyncio.to_thread(library.feed, self._stream, block)
                    )
                if self._said and time.monotonic() - self._spoke_at >= self._SILENCE:
                    await self._settle(library)
        finally:
            # Closing must not raise: the stream is already going away.
            with contextlib.suppress(Exception):
                await self._settle(library)
