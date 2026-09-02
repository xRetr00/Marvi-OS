"""What every STT runner needs and none of them should own a copy of.

The first round grew four runners, each with its own `_gpu_memory_mb`, its own
Windows `GetProcessMemoryInfo` struct, and its own manifest loop. Four copies
of a measurement is four chances for two engines to be measured differently,
which is the one thing a bakeoff cannot survive.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import time
import wave
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any


def gpu_memory_mb() -> float:
    """Device memory in use, from the driver rather than an allocator.

    `torch.cuda.max_memory_allocated` sees only what Torch allocated; ONNX
    Runtime, CTranslate2 and a Rust binary allocate outside it, and a bakeoff
    across those cannot compare numbers from different sides of that line.
    """
    try:
        found = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            check=True,
            capture_output=True,
            text=True,
        )
        return float(found.stdout.splitlines()[0].strip())
    except Exception:  # noqa: BLE001 - a CPU-only run has no device to report
        return 0.0


class _Counters(ctypes.Structure):
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


def peak_rss_mb() -> float:
    """Peak working set of this process. Windows, because that is the target."""
    counters = _Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    handle = kernel32.GetCurrentProcess()
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_Counters),
        ctypes.c_ulong,
    ]
    ctypes.windll.psapi.GetProcessMemoryInfo.restype = ctypes.c_bool
    if not ctypes.windll.psapi.GetProcessMemoryInfo(
        handle, ctypes.byref(counters), counters.cb
    ):
        raise ctypes.WinError()
    return counters.PeakWorkingSetSize / (1024 * 1024)


def read_pcm16(path: Path) -> tuple[bytes, float]:
    """The clip's bytes and its length. 16 kHz mono is what the corpus writes."""
    with wave.open(str(path), "rb") as source:
        if source.getframerate() != 16_000 or source.getnchannels() != 1:
            raise RuntimeError(f"{path.name} is not 16 kHz mono")
        frames = source.getnframes()
        return source.readframes(frames), frames / 16_000.0


def run(
    manifest_path: Path,
    corpus: Path,
    output: Path,
    engine: str,
    semantics: str,
    transcribe: Callable[[Path], dict[str, Any]],
    load_seconds: float,
    baseline_vram: float,
    limit: int | None = None,
) -> None:
    """Drive one engine over the manifest, writing one JSONL row per clip.

    Every runner reports the same fields with the same meaning, because
    `stt_score.py` reads them and a field that means something different in one
    runner is a column that lies in the table.

    A clip that raises is written as an empty hypothesis with the error on the
    row, rather than left out. Kyutai returned nothing for five clips in the
    first round and the missing 59 reference words became deletions inside its
    accuracy number -- 8.7 of its 46.6 WER points were a harness failure
    wearing a model's name. Recorded, they can be counted as what they are.
    """
    manifest = [
        json.loads(line)
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
    ]
    if limit is not None:
        manifest = manifest[:limit]
    peak_vram = gpu_memory_mb()
    failures = 0
    with output.open("w", encoding="utf-8") as sink:
        for index, item in enumerate(manifest, start=1):
            clip = corpus / str(item["audio"])
            try:
                result: dict[str, Any] = transcribe(clip)
                error = ""
            except Exception as exc:  # noqa: BLE001 - one clip cannot end a run
                failures += 1
                _, seconds = read_pcm16(clip)
                result = {
                    "text": "",
                    "inference_seconds": 0.0,
                    "first_partial_ms": None,
                    "final_after_eos_ms": None,
                    "partials": 0,
                    "audio_seconds": seconds,
                }
                error = str(exc)[:300]
            peak_vram = max(peak_vram, gpu_memory_mb())
            sink.write(
                json.dumps(
                    {
                        "id": item["id"],
                        "engine": engine,
                        **result,
                        "error": error,
                        "model_load_seconds": load_seconds,
                        "peak_rss_mb": peak_rss_mb(),
                        "peak_vram_mb": max(0.0, peak_vram - baseline_vram),
                        "streaming_semantics": semantics,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            sink.flush()
            said = str(result.get("text") or "")
            print(
                f"[{index}/{len(manifest)}] {item['id']}: "
                f"{(error and 'FAILED: ' + error) or said}",
                flush=True,
            )
    if failures:
        print(f"\n{failures} of {len(manifest)} clips failed outright", flush=True)


def timed(build: Callable[[], Any]) -> tuple[Any, float, float]:
    """Load a model, reporting how long it took and the device baseline."""
    baseline = gpu_memory_mb()
    began = time.perf_counter()
    built = build()
    return built, time.perf_counter() - began, baseline


def clips(manifest_path: Path) -> Iterable[dict[str, Any]]:
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        yield json.loads(line)
