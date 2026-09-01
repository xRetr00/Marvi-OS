"""Drive qwen3-asr-rs rolling streaming sessions over the accented corpus."""

from __future__ import annotations

import argparse
import array
import base64
import io
import json
import time
import urllib.request
import wave
from pathlib import Path

import psutil


def post(base_url: str, route: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        f"{base_url}{route}",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.load(response)


def audio(path: Path) -> list[int]:
    with wave.open(str(path), "rb") as source:
        if (
            source.getframerate() != 16_000
            or source.getnchannels() != 1
            or source.getsampwidth() != 2
        ):
            raise ValueError(f"{path} must be 16 kHz mono signed 16-bit PCM")
        samples = array.array("h", source.readframes(source.getnframes()))
    return samples.tolist()


def data_url(samples: list[int]) -> str:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(array.array("h", samples).tobytes())
    return "data:audio/wav;base64," + base64.b64encode(stream.getvalue()).decode()


def server_process() -> psutil.Process:
    matches = [
        process
        for process in psutil.process_iter(("name",))
        if process.info["name"] == "qwen3-asr.exe"
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one qwen3-asr.exe server, found {len(matches)}")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:18765")
    args = parser.parse_args()
    manifest = [
        json.loads(line)
        for line in args.manifest.read_text(encoding="utf-8").splitlines()
    ]
    process = server_process()
    chunk_samples = 32_000

    with args.output.open("w", encoding="utf-8") as output:
        for item in manifest:
            samples = audio(args.corpus / item["audio"])
            start = post(
                args.base_url,
                "/v1/stream/start",
                {
                    "language": "English",
                    "chunk_size_sec": 2.0,
                    "audio_window_sec": 8.0,
                    "text_window_tokens": 256,
                    "unfixed_chunk_num": 2,
                    "unfixed_token_num": 5,
                    "max_new_tokens": 128,
                },
            )
            session_id = start["session_id"]
            inference_seconds = 0.0
            first_partial_ms = None
            partials = 0
            for offset in range(0, len(samples), chunk_samples):
                chunk = samples[offset : offset + chunk_samples]
                started = time.perf_counter()
                update = post(
                    args.base_url,
                    "/v1/stream/push",
                    {"session_id": session_id, "audio": data_url(chunk)},
                )
                inference_seconds += time.perf_counter() - started
                state = update.get("partial") or update.get("state")
                if state and state.get("text"):
                    partials += 1
                    if first_partial_ms is None:
                        audio_ms = min(offset + len(chunk), len(samples)) / 16.0
                        first_partial_ms = audio_ms + inference_seconds * 1_000.0
            started = time.perf_counter()
            final = post(
                args.base_url,
                "/v1/stream/finish",
                {"session_id": session_id},
            )
            final_after_eos_ms = (time.perf_counter() - started) * 1_000.0
            inference_seconds += final_after_eos_ms / 1_000.0
            memory = process.memory_info()
            record = {
                "id": item["id"],
                "engine": "qwen3-asr-0.6b-rust-rolling-cpu-f32",
                "text": final["final"]["text"],
                "audio_seconds": len(samples) / 16_000.0,
                "inference_seconds": inference_seconds,
                "first_partial_ms": first_partial_ms,
                "final_after_eos_ms": final_after_eos_ms,
                "partials": partials,
                "feed_ms": 2_000,
                "peak_rss_mb": memory.rss / (1024 * 1024),
                "peak_vram_mb": 0,
                "streaming_semantics": "rolling-8s-audio-prefix-rollback",
            }
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()


if __name__ == "__main__":
    main()
