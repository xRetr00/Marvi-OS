"""Benchmark Whisper large-v3-turbo through WhisperLiveKit SimulStreaming."""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np


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


def _read_pcm16_mono(path: Path) -> tuple[np.ndarray, float]:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1:
            raise ValueError(f"expected mono WAV: {path}")
        if source.getsampwidth() != 2:
            raise ValueError(f"expected PCM16 WAV: {path}")
        if source.getframerate() != 16_000:
            raise ValueError(f"expected 16 kHz WAV: {path}")
        frame_count = source.getnframes()
        pcm = np.frombuffer(source.readframes(frame_count), dtype="<i2")
    return pcm.astype(np.float32) / 32768.0, frame_count / 16_000.0


class WhisperLiveKitStreamingStt:
    def __init__(self, encoder_model: Path, decoder_cache: Path, vac: bool = True) -> None:
        from whisperlivekit.core import TranscriptionEngine
        from whisperlivekit.simul_whisper.backend import (
            SimulStreamingOnlineProcessor,
        )

        self.processor_type = SimulStreamingOnlineProcessor
        TranscriptionEngine.reset()
        self.engine = TranscriptionEngine(
            backend_policy="simulstreaming",
            backend="faster-whisper",
            model_size="large-v3-turbo",
            encoder_model_path=str(encoder_model.resolve()),
            model_cache_dir=str(decoder_cache.resolve()),
            lan="en",
            min_chunk_size=0.1,
            # VAC is upstream's own default (`config.py`: `vac: bool = True`)
            # and the first round ran without it, because this driver builds the
            # processor directly and never goes through `AudioProcessor` -- the
            # only place that consults it. So large-v3-turbo transcribed silence
            # as well as speech for every clip, which is most of what a voice
            # activity controller exists to prevent and most of why the measured
            # RTF was 2.747. A "slower than realtime" verdict taken from a
            # configuration the library does not ship is not a verdict.
            vac=vac,
            vac_chunk_size=0.04,
            frame_threshold=25,
            beams=1,
            decoder_type="greedy",
            vad=False,
            diarization=False,
        )
        self.asr = self.engine.asr
        if self.asr.encoder_backend != "faster-whisper":
            raise RuntimeError(
                f"expected faster-whisper encoder, got {self.asr.encoder_backend}"
            )

    def transcribe(self, audio_path: Path) -> dict[str, object]:
        audio, audio_seconds = _read_pcm16_mono(audio_path)
        processor = self.processor_type(self.asr)
        chunk_samples = 1_600
        pieces: list[str] = []
        compute_seconds = 0.0
        first_partial_ms: float | None = None
        partials = 0

        for offset in range(0, audio.size, chunk_samples):
            chunk = np.ascontiguousarray(audio[offset : offset + chunk_samples])
            presented_samples = min(offset + chunk.size, audio.size)
            stream_end = presented_samples / 16_000.0
            processor.insert_audio_chunk(chunk, stream_end)
            started = time.perf_counter()
            tokens, _ = processor.process_iter(is_last=False)
            compute_seconds += time.perf_counter() - started
            emitted = "".join(token.text for token in tokens)
            if emitted:
                pieces.append(emitted)
                partials += 1
                if first_partial_ms is None and emitted.strip():
                    first_partial_ms = stream_end * 1_000.0 + compute_seconds * 1_000.0

        final_started = time.perf_counter()
        final_tokens, _ = processor.process_iter(is_last=True)
        final_seconds = time.perf_counter() - final_started
        compute_seconds += final_seconds
        final_text = "".join(token.text for token in final_tokens)
        if final_text:
            pieces.append(final_text)
            partials += 1
            if first_partial_ms is None and final_text.strip():
                first_partial_ms = audio_seconds * 1_000.0 + compute_seconds * 1_000.0

        return {
            "text": "".join(pieces),
            "inference_seconds": compute_seconds,
            "first_partial_ms": first_partial_ms,
            "final_after_eos_ms": final_seconds * 1_000.0,
            "partials": partials,
            "audio_seconds": audio_seconds,
            "feed_ms": 100.0,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("encoder_model", type=Path)
    parser.add_argument("decoder_cache", type=Path)
    parser.add_argument("cuda_runtime", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int)
    # VAC is upstream's default and the shipped configuration, so it is the
    # default here. It is a flag rather than a constant because this venv has
    # no `onnxruntime`, and without it WhisperLiveKit loads the VAC model from
    # TorchScript *per session* -- the runner builds a processor per clip, so
    # that is a fresh JIT load 162 times, and the run went from minutes to
    # hours. The accuracy question does not depend on it: these clips are
    # pre-segmented speech with little silence for a voice-activity controller
    # to skip. The realtime-factor question does.
    parser.add_argument("--no-vac", dest="vac", action="store_false")
    args = parser.parse_args()

    manifest = [
        json.loads(line)
        for line in args.manifest.read_text(encoding="utf-8").splitlines()
    ]
    if args.limit is not None:
        manifest = manifest[: args.limit]
    if not manifest:
        raise ValueError("manifest contains no evaluation items")

    logging.getLogger("whisperlivekit").setLevel(logging.WARNING)

    cuda_runtime = args.cuda_runtime.resolve()
    if not (cuda_runtime / "cublas64_12.dll").is_file():
        raise FileNotFoundError(f"CUDA 12 BLAS runtime not found under {cuda_runtime}")
    runtime_marker = str(cuda_runtime).casefold()
    if os.environ.get("MARVI_WLK_CUDA_RUNTIME", "").casefold() != runtime_marker:
        child_environment = os.environ.copy()
        child_environment["PATH"] = f"{cuda_runtime};{child_environment['PATH']}"
        child_environment["MARVI_WLK_CUDA_RUNTIME"] = str(cuda_runtime)
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
            env=child_environment,
            check=False,
        )
        raise SystemExit(completed.returncode)
    dll_directory = os.add_dll_directory(str(cuda_runtime))

    baseline_vram = _gpu_memory_mb()
    load_started = time.perf_counter()
    runtime = WhisperLiveKitStreamingStt(args.encoder_model, args.decoder_cache, args.vac)
    load_seconds = time.perf_counter() - load_started
    peak_vram = _gpu_memory_mb()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output:
        for index, item in enumerate(manifest, start=1):
            result = runtime.transcribe(args.corpus / item["audio"])
            peak_vram = max(peak_vram, _gpu_memory_mb())
            record = {
                "id": item["id"],
                "engine": (
                    "whisper-large-v3-turbo-whisperlivekit-0.2.26-"
                    "b781ce9-simulstreaming-faster-whisper-cuda"
                ),
                **result,
                "model_load_seconds": load_seconds,
                "peak_rss_mb": _peak_rss_mb(),
                "peak_vram_mb": max(0.0, peak_vram - baseline_vram),
                "streaming_semantics": (
                    "alignatt-simulstreaming-100ms-updates-"
                    + ("vac" if args.vac else "novac")
                ),
            }
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()
            print(
                f"[{index}/{len(manifest)}] {item['id']}: {result['text']}",
                flush=True,
            )
    dll_directory.close()


if __name__ == "__main__":
    main()
