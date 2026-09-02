"""Run a pinned parakeet.cpp C API model over Marvi's streaming STT corpus."""

from __future__ import annotations

import _ctypes
import argparse
import array
import ctypes
import json
import os
import subprocess
import time
import wave
from pathlib import Path


def _gpu_memory_mb() -> float:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.splitlines()[0].strip())


class ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _peak_rss_mb() -> float:
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    process = ctypes.windll.kernel32.GetCurrentProcess()
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ProcessMemoryCounters),
        ctypes.c_ulong,
    ]
    ctypes.windll.psapi.GetProcessMemoryInfo.restype = ctypes.c_bool
    if not ctypes.windll.psapi.GetProcessMemoryInfo(
        process, ctypes.byref(counters), counters.cb
    ):
        raise ctypes.WinError()
    return counters.PeakWorkingSetSize / (1024 * 1024)


def _audio(path: Path) -> list[float]:
    with wave.open(str(path), "rb") as source:
        if source.getframerate() != 16_000 or source.getnchannels() != 1:
            raise ValueError(f"{path} must be 16 kHz mono")
        if source.getsampwidth() != 2:
            raise ValueError(f"{path} must contain signed 16-bit PCM")
        pcm = array.array("h", source.readframes(source.getnframes()))
    return [sample / 32_768.0 for sample in pcm]


class ParakeetCpp:
    def __init__(self, dll: Path, model: Path, language: str) -> None:
        os.add_dll_directory(str(dll.parent))
        self.library = ctypes.CDLL(str(dll))
        self.library.parakeet_capi_abi_version.restype = ctypes.c_int
        if self.library.parakeet_capi_abi_version() != 6:
            raise RuntimeError("parakeet.cpp C API ABI is not v6")
        self.library.parakeet_capi_load.argtypes = [ctypes.c_char_p]
        self.library.parakeet_capi_load.restype = ctypes.c_void_p
        self.library.parakeet_capi_free.argtypes = [ctypes.c_void_p]
        self.library.parakeet_capi_last_error.argtypes = [ctypes.c_void_p]
        self.library.parakeet_capi_last_error.restype = ctypes.c_char_p
        self.library.parakeet_capi_stream_begin_lang.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
        ]
        self.library.parakeet_capi_stream_begin_lang.restype = ctypes.c_void_p
        self.library.parakeet_capi_stream_feed_json.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_int,
        ]
        self.library.parakeet_capi_stream_feed_json.restype = ctypes.c_void_p
        self.library.parakeet_capi_stream_finalize_json.argtypes = [ctypes.c_void_p]
        self.library.parakeet_capi_stream_finalize_json.restype = ctypes.c_void_p
        self.library.parakeet_capi_stream_free.argtypes = [ctypes.c_void_p]
        self.library.parakeet_capi_free_string.argtypes = [ctypes.c_void_p]
        self.language = language.encode()
        self.context = self.library.parakeet_capi_load(str(model).encode())
        if not self.context:
            raise RuntimeError("parakeet.cpp failed to load the model")

    def close(self) -> None:
        if self.context:
            self.library.parakeet_capi_free(self.context)
            self.context = None
        if self.library:
            _ctypes.FreeLibrary(self.library._handle)
            self.library = None

    def _error(self) -> RuntimeError:
        return RuntimeError(
            self.library.parakeet_capi_last_error(self.context).decode()
        )

    def _json(self, pointer: int | None) -> dict[str, object]:
        if not pointer:
            raise self._error()
        try:
            return json.loads(ctypes.string_at(pointer).decode())
        finally:
            self.library.parakeet_capi_free_string(pointer)

    def transcribe(self, audio: list[float], feed_samples: int) -> dict[str, object]:
        stream = self.library.parakeet_capi_stream_begin_lang(
            self.context, self.language
        )
        if not stream:
            raise self._error()
        text: list[str] = []
        events: list[dict[str, object]] = []
        compute_seconds = 0.0
        first_partial_ms = None
        partials = 0
        try:
            for offset in range(0, len(audio), feed_samples):
                values = audio[offset : offset + feed_samples]
                buffer = (ctypes.c_float * len(values))(*values)
                started = time.perf_counter()
                update = self._json(
                    self.library.parakeet_capi_stream_feed_json(
                        stream, buffer, len(values)
                    )
                )
                compute_seconds += time.perf_counter() - started
                if update["text"]:
                    text.append(str(update["text"]))
                    partials += 1
                    if first_partial_ms is None:
                        audio_ms = min(offset + len(values), len(audio)) / 16.0
                        first_partial_ms = audio_ms + compute_seconds * 1_000.0
                events.extend(update["events"])
            started = time.perf_counter()
            update = self._json(self.library.parakeet_capi_stream_finalize_json(stream))
            final_after_eos_ms = (time.perf_counter() - started) * 1_000.0
            compute_seconds += final_after_eos_ms / 1_000.0
            if update["text"]:
                text.append(str(update["text"]))
                partials += 1
            events.extend(update["events"])
        finally:
            self.library.parakeet_capi_stream_free(stream)
        return {
            "text": "".join(text),
            "inference_seconds": compute_seconds,
            "first_partial_ms": first_partial_ms,
            "final_after_eos_ms": final_after_eos_ms,
            "partials": partials,
            "eou_events": sum(event["type"] == "eou" for event in events),
            "eob_events": sum(event["type"] == "eob" for event in events),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", choices=("eou", "nemotron"))
    parser.add_argument("manifest", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("dll", type=Path)
    parser.add_argument("cudart", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    os.add_dll_directory(str(args.cudart.resolve()))
    manifest = [
        json.loads(line)
        for line in args.manifest.read_text(encoding="utf-8").splitlines()
    ]
    baseline_vram = _gpu_memory_mb()
    load_started = time.perf_counter()
    runtime = ParakeetCpp(args.dll.resolve(), args.model.resolve(), "en-US")
    load_seconds = time.perf_counter() - load_started
    peak_vram = _gpu_memory_mb()
    engine_name = (
        "parakeet-realtime-eou-120m-parakeet.cpp-v0.5.0-cuda-f16"
        if args.engine == "eou"
        else "nemotron-3.5-streaming-0.6b-parakeet.cpp-v0.5.0-cuda-f16"
    )
    feed_samples = 2_560 if args.engine == "eou" else 5_120
    try:
        with args.output.open("w", encoding="utf-8") as output:
            for item in manifest:
                audio = _audio(args.corpus / item["audio"])
                result = runtime.transcribe(audio, feed_samples=feed_samples)
                peak_vram = max(peak_vram, _gpu_memory_mb())
                record = {
                    "id": item["id"],
                    "engine": engine_name,
                    **result,
                    "audio_seconds": len(audio) / 16_000.0,
                    "feed_ms": feed_samples / 16,
                    "model_load_seconds": load_seconds,
                    "peak_rss_mb": _peak_rss_mb(),
                    "peak_vram_mb": max(0.0, peak_vram - baseline_vram),
                    "streaming_semantics": "cache-aware-rnnt",
                }
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
