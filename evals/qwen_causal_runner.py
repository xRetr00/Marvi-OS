"""Benchmark Qwen3-ASR causal streaming with one shared model and fresh sessions."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import psutil
import soundfile as sf
import torch
from qwen3_asr_causal import Qwen3StreamingASR, Qwen3StreamingOnlineProcessor


def gpu_memory_mb() -> float:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.splitlines()[0].strip())


def load_audio(path: Path) -> np.ndarray:
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=False)
    if sample_rate != 16_000 or audio.ndim != 1:
        raise ValueError(f"{path} must be 16 kHz mono")
    return np.asarray(audio, dtype=np.float32)


def transcribe(asr: Qwen3StreamingASR, audio: np.ndarray) -> dict[str, object]:
    processor = Qwen3StreamingOnlineProcessor(asr)
    feed_samples = 8_000
    tokens = []
    inference_seconds = 0.0
    first_partial_ms = None
    partial_updates = 0
    for start in range(0, len(audio), feed_samples):
        chunk = audio[start : start + feed_samples]
        end_time = min(len(audio), start + len(chunk)) / 16_000
        processor.insert_audio_chunk(chunk, end_time)
        started = time.perf_counter()
        new_tokens, _ = processor.process_iter(is_last=False)
        inference_seconds += time.perf_counter() - started
        if new_tokens:
            tokens.extend(new_tokens)
            partial_updates += 1
            if first_partial_ms is None:
                first_partial_ms = end_time * 1_000.0 + inference_seconds * 1_000.0
    started = time.perf_counter()
    final_tokens, _ = processor.finish()
    final_after_eos_ms = (time.perf_counter() - started) * 1_000.0
    inference_seconds += final_after_eos_ms / 1_000.0
    tokens.extend(final_tokens)
    text = " ".join(
        (token.text or "").strip() for token in tokens if (token.text or "").strip()
    )
    return {
        "text": text,
        "inference_seconds": inference_seconds,
        "first_partial_ms": first_partial_ms,
        "final_after_eos_ms": final_after_eos_ms,
        "partials": partial_updates,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("base_model", type=Path)
    parser.add_argument("causal_tower", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    manifest = [
        json.loads(line)
        for line in args.manifest.read_text(encoding="utf-8").splitlines()
    ]
    baseline_vram = gpu_memory_mb()
    load_started = time.perf_counter()
    asr = Qwen3StreamingASR(
        lan="en",
        model_size=str(args.base_model.resolve()),
        qwen3_streaming_audio_backend="causal",
        qwen3_streaming_tower_checkpoint=str(args.causal_tower.resolve()),
        qwen3_streaming_device="cuda",
        qwen3_streaming_dtype="bfloat16",
        qwen3_streaming_chunk_sec=2.0,
        qwen3_streaming_left_context_sec=15.0,
        qwen3_streaming_block_frames=192,
    )
    load_seconds = time.perf_counter() - load_started
    # Warm kernels and allocator buckets without carrying session state into the corpus.
    transcribe(asr, load_audio(args.corpus / manifest[0]["audio"]))
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    peak_global_vram = gpu_memory_mb()
    process = psutil.Process()

    with args.output.open("w", encoding="utf-8") as output:
        for item in manifest:
            audio = load_audio(args.corpus / item["audio"])
            result = transcribe(asr, audio)
            torch.cuda.synchronize()
            peak_global_vram = max(peak_global_vram, gpu_memory_mb())
            memory = process.memory_info()
            record = {
                "id": item["id"],
                "engine": "qwen3-asr-0.6b-causal-hf-cuda-bf16",
                **result,
                "audio_seconds": len(audio) / 16_000.0,
                "feed_ms": 500,
                "model_load_seconds": load_seconds,
                "peak_rss_mb": memory.rss / (1024 * 1024),
                "peak_vram_mb": max(0.0, peak_global_vram - baseline_vram),
                "torch_peak_allocated_mb": torch.cuda.max_memory_allocated()
                / (1024 * 1024),
                "streaming_semantics": "append-only-causal-kv-1920ms-blocks",
            }
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()


if __name__ == "__main__":
    main()
