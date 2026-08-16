from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import wave
from pathlib import Path

import numpy as np
from marvi_agent.voice_models import DEFAULT_VOICE, VIBEVOICE_ROOT, _VibeVoiceEngine
from scipy.signal import resample_poly


def send(process: subprocess.Popen[str], payload: dict[str, str]) -> dict[str, object]:
    assert process.stdin and process.stdout
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()
    return json.loads(process.stdout.readline())


def main() -> None:
    import torch

    repo = Path(__file__).resolve().parents[1]
    app_data = Path(os.environ["LOCALAPPDATA"]) / "Marvi-OS"
    diagnostic_dir = app_data / "diagnostics"
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    text = "Hello, I am Marvi. The native realtime voice system is online."
    engine = _VibeVoiceEngine(
        VIBEVOICE_ROOT / "model", VIBEVOICE_ROOT / "voices", DEFAULT_VOICE, 3
    )

    started = time.perf_counter()
    engine.load()
    load_seconds = time.perf_counter() - started
    torch.cuda.reset_peak_memory_stats()
    chunks: list[bytes] = []
    tts_started = time.perf_counter()
    first_chunk_seconds: float | None = None
    import threading

    for chunk in engine.synthesize(text, threading.Event()):
        if first_chunk_seconds is None:
            first_chunk_seconds = time.perf_counter() - tts_started
        chunks.append(chunk)
    tts_seconds = time.perf_counter() - tts_started
    pcm24 = b"".join(chunks)
    audio_seconds = len(pcm24) / 2 / 24_000
    wav_path = diagnostic_dir / "phase-3-vibevoice.wav"
    with wave.open(str(wav_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24_000)
        output.writeframes(pcm24)

    audio24 = np.frombuffer(pcm24, dtype=np.int16).astype(np.float32) / 32768.0
    audio16 = np.clip(resample_poly(audio24, 2, 3), -1, 1)
    pcm16 = (audio16 * 32767).astype(np.int16).tobytes()
    executable = repo / "services/voice-runtime/target/release/marvi-voice-runtime.exe"
    model = app_data / "models/stt/nemotron-3.5/nemotron-3.5-asr-streaming-0.6b-onnx"
    process = subprocess.Popen(
        [str(executable), str(model), "en-US"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert process.stdout
    ready = json.loads(process.stdout.readline())
    asr_started = time.perf_counter()
    transcript = ""
    for offset in range(0, len(pcm16), 8960 * 2):
        response = send(
            process,
            {
                "op": "audio",
                "pcm16": base64.b64encode(pcm16[offset : offset + 8960 * 2]).decode(),
            },
        )
        transcript += str(response.get("text", ""))
    transcript += str(send(process, {"op": "flush"}).get("text", ""))
    asr_seconds = time.perf_counter() - asr_started
    process.stdin.close() if process.stdin else None
    process.wait(timeout=10)

    gpu = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    used_mib, total_mib = (int(value.strip()) for value in gpu.split(","))
    evidence = {
        "hardware": {
            "gpu": torch.cuda.get_device_name(0),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "gpu_memory_mib_after_bakeoff": used_mib,
            "gpu_total_mib": total_mib,
        },
        "tts": {
            "model": "microsoft/VibeVoice-Realtime-0.5B",
            "voice": DEFAULT_VOICE,
            "load_seconds": round(load_seconds, 3),
            "first_audio_seconds": round(first_chunk_seconds or 0, 3),
            "generation_seconds": round(tts_seconds, 3),
            "audio_seconds": round(audio_seconds, 3),
            "realtime_factor": round(tts_seconds / audio_seconds, 3),
            "torch_peak_vram_mib": round(torch.cuda.max_memory_allocated() / 1024**2),
            "wav": str(wav_path),
        },
        "stt": {
            "model": "nvidia/nemotron-3.5-asr-streaming-0.6b",
            "runtime": "parakeet-rs 0.3.7 CUDA",
            "audio_seconds": round(audio_seconds, 3),
            "transcription_seconds": round(asr_seconds, 3),
            "realtime_factor": round(asr_seconds / audio_seconds, 3),
            "transcript": transcript.strip(),
        },
        "source_text": text,
        "ready": ready,
    }
    evidence_path = repo / "docs/evidence/phase-3-hardware-bakeoff.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
