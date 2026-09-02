"""Run Kyutai STT 1B over Marvi's accented-English streaming corpus."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import time
import wave
from pathlib import Path

os.environ.setdefault("NO_TORCH_COMPILE", "1")

import sentencepiece
import sphn
import torch
from moshi.models import LMGen, LMModel, MimiModel, loaders


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


class KyutaiStreamingStt:
    def __init__(self, model_dir: Path) -> None:
        checkpoint = loaders.CheckpointInfo.from_hf_repo(
            "kyutai/stt-1b-en_fr",
            config_path=model_dir / "config.json",
            moshi_weights=model_dir / "model.safetensors",
            mimi_weights=model_dir / "mimi-pytorch-e351c8d8@125.safetensors",
            tokenizer=model_dir / "tokenizer_en_fr_audio_8000.model",
        )
        self.mimi: MimiModel = checkpoint.get_mimi(device="cuda")
        self.tokenizer: sentencepiece.SentencePieceProcessor = (
            checkpoint.get_text_tokenizer()
        )
        self.lm: LMModel = checkpoint.get_moshi(device="cuda")
        self.lm_gen = LMGen(self.lm, temp=0, temp_text=0, use_sampling=False)
        self.frame_size = int(self.mimi.sample_rate / self.mimi.frame_rate)
        self.flush_samples = int(
            (float(checkpoint.stt_config["audio_delay_seconds"]) + 1.0)
            * self.mimi.sample_rate
        )
        # Silence before the speech, and this is the whole reason the first
        # round scored this model at 40.73% with eleven empty clips.
        #
        # Fed audio that begins with a word already in progress, the model
        # emits nothing at all. Measured directly on the six clips that came
        # back empty: isolated, all six produced nothing; with one second of
        # silence in front, all six produced correct transcripts --
        #
        #   ref  UH IT'S BASICALLY LIKE A WEB PAGE LINK IT'S NOT REALLY AN APP
        #   was  (nothing)
        #   now  It's basically like a web pa...
        #
        # The checkpoint's own `audio_silence_prefix_seconds` is 0.0, which is
        # what made this easy to miss, but Kyutai's demo never starts mid-word:
        # the stream is open and quiet before anyone speaks. A benchmark that
        # starts the audio at the first syllable is not testing the model, it
        # is testing an entrance nobody uses.
        self.prefix_samples = int(
            max(float(checkpoint.stt_config.get("audio_silence_prefix_seconds", 0.0)), 1.0)
            * self.mimi.sample_rate
        )
        self.mimi.streaming_forever(1)
        self.lm_gen.streaming_forever(1)

    @torch.inference_mode()
    def transcribe(self, audio_path: Path) -> dict[str, object]:
        with wave.open(str(audio_path), "rb") as source:
            input_audio_seconds = source.getnframes() / source.getframerate()
        pcm, _ = sphn.read(str(audio_path), sample_rate=self.mimi.sample_rate)
        audio = torch.from_numpy(pcm[None, 0:1]).to(device="cuda")
        audio_samples = audio.shape[-1] + self.prefix_samples
        input_audio_samples = round(input_audio_seconds * self.mimi.sample_rate)
        audio = torch.nn.functional.pad(
            audio, (self.prefix_samples, self.flush_samples)
        )
        self.mimi.reset_streaming()
        self.lm_gen.reset_streaming()
        pieces: list[str] = []
        compute_seconds = 0.0
        first_partial_ms: float | None = None
        partials = 0
        first_frame = True
        input_compute_seconds = 0.0
        frames = 0

        for offset in range(0, audio.shape[-1], self.frame_size):
            chunk = audio[:, :, offset : offset + self.frame_size]
            if chunk.shape[-1] != self.frame_size:
                break
            started = time.perf_counter()
            codes = self.mimi.encode(chunk)
            if first_frame:
                self.lm_gen.step(codes)
                first_frame = False
            tokens = self.lm_gen.step(codes)
            # Wait for the GPU before stopping the clock.
            #
            # Without this the loop times how long it takes to *queue* work,
            # not to do it, because every CUDA call here returns immediately.
            # It is why the first round reported RTF 0.244 for a model that
            # actually spends 60ms on an 80ms frame. Measured both ways over
            # 48 decodes: 59.3 ms/frame with one sync per clip, 78.7 ms/frame
            # syncing every frame, and 24 ms/frame syncing never -- the last
            # of which is not a measurement of anything.
            #
            # Per frame rather than per clip, because that is the question a
            # streaming recogniser has to answer: audio arrives every 80ms and
            # there is no running ahead of a microphone.
            torch.cuda.synchronize()
            elapsed = time.perf_counter() - started
            compute_seconds += elapsed
            frames += 1
            if offset < audio_samples:
                input_compute_seconds += elapsed
            if tokens is None:
                continue
            token_id = int(tokens[0, 0].cpu().item())
            if token_id in (0, 3):
                continue
            piece = self.tokenizer.id_to_piece(token_id).replace("▁", " ")
            pieces.append(piece)
            partials += 1
            if first_partial_ms is None and piece.strip():
                presented_samples = min(offset + self.frame_size, input_audio_samples)
                first_partial_ms = (
                    presented_samples / self.mimi.sample_rate * 1_000.0
                    + compute_seconds * 1_000.0
                )

        final_compute_seconds = compute_seconds - input_compute_seconds
        return {
            "text": "".join(pieces),
            "inference_seconds": compute_seconds,
            "first_partial_ms": first_partial_ms,
            "final_after_eos_ms": final_compute_seconds * 1_000.0,
            "partials": partials,
            "audio_seconds": input_audio_seconds,
            "feed_ms": self.frame_size / self.mimi.sample_rate * 1_000.0,
            # The number that decides whether it keeps up: compute per frame
            # against the 80ms the frame represents.
            "ms_per_frame": compute_seconds / max(frames, 1) * 1_000.0,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    manifest = [
        json.loads(line)
        for line in args.manifest.read_text(encoding="utf-8").splitlines()
    ]
    if args.limit is not None:
        manifest = manifest[: args.limit]
    baseline_vram = _gpu_memory_mb()
    load_started = time.perf_counter()
    runtime = KyutaiStreamingStt(args.model.resolve())
    load_seconds = time.perf_counter() - load_started
    peak_vram = _gpu_memory_mb()

    with args.output.open("w", encoding="utf-8") as output:
        for index, item in enumerate(manifest, start=1):
            result = runtime.transcribe(args.corpus / item["audio"])
            peak_vram = max(peak_vram, _gpu_memory_mb())
            record = {
                "id": item["id"],
                "engine": "kyutai-stt-1b-en-fr-moshi-0.2.13-cuda-bf16",
                **result,
                "model_load_seconds": load_seconds,
                "peak_rss_mb": _peak_rss_mb(),
                "peak_vram_mb": max(0.0, peak_vram - baseline_vram),
                "streaming_semantics": "causal-mimi-80ms-frames",
            }
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()
            print(
                f"[{index}/{len(manifest)}] {item['id']}: {result['text']}", flush=True
            )


if __name__ == "__main__":
    main()
