"""Pipecat's voice-agent STT benchmark corpus, in Marvi's manifest format.

Every corpus we have measured against so far is the wrong shape for Marvi.
EdAcc is spontaneous conversation between two people, five seconds a clip;
L2-ARCTIC is read CMU prompts. Neither is somebody talking *to an assistant*,
and the failure the owner keeps hitting -- Marvi going quiet on a short answer
-- lives entirely in that gap. A recogniser can be excellent at five seconds of
conversational English and still lose "yeah, go ahead".

Pipecat built their benchmark out of exactly those turns: 1,000 samples drawn
from `smart-turn-data-v3.1-train`, which is voice-agent audio, with ground
truth generated and then human-reviewed. Median duration is a little over three
seconds. That is the distribution Marvi actually serves.

So this is not a third accent corpus. It is the first corpus here that matches
the job.

## What is kept and what is not

Pipecat's own runner streams to hosted services over a websocket and measures
against their VAD. We cannot reuse that: our engines are in-process, and the
numbers would not be comparable to the three rounds already recorded. What we
take is the *audio and the references*, converted into the same manifest every
other corpus here uses, so the existing runners work unchanged and the results
sit in the same table.

The full thousand is more than a local round needs and biases nothing if
sampled stably, so `--limit` selects by a hash of the sample id -- the same
trick the EdAcc builder uses, and for the same reason: re-running picks the
same clips.

    python evals/pipecat_corpus.py <destination> [--limit 200]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import wave
from pathlib import Path

DATASET = "pipecat-ai/stt-benchmark-data"
FILE = "data/train-00000-of-00001.parquet"

#: How many of the thousand to take. Two hundred is about 700 seconds of audio,
#: which is the same order as the EdAcc round, and the runners take minutes
#: rather than an hour on the slower engines.
DEFAULT_LIMIT = 200

#: Clips shorter than this are silence or a click, and clips longer than this
#: are not the short-utterance case the corpus exists to measure.
SHORTEST = 0.4
LONGEST = 20.0


def _pick(sample_id: str) -> int:
    """A stable order that does not depend on the file's row order."""
    return int(hashlib.sha256(sample_id.encode()).hexdigest()[:12], 16)


def main() -> None:
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()

    path = hf_hub_download(
        DATASET, FILE, repo_type="dataset", token=os.environ.get("HF_TOKEN")
    )
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows.sort(key=lambda row: _pick(row["sample_id"]))

    args.destination.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    for row in rows:
        if len(manifest) >= args.limit:
            break
        reference = str(row["transcription"] or "").strip()
        duration = float(row["duration_seconds"])
        if not reference or not SHORTEST <= duration <= LONGEST:
            continue
        audio = row["audio"]["bytes"]
        name = f"pipecat-{row['sample_id'][:8]}.wav"
        (args.destination / name).write_bytes(audio)
        with wave.open(str(args.destination / name), "rb") as source:
            # Trust the file over the column: the runners read frames, and a
            # duration that disagrees with them lands straight in the RTF.
            duration = source.getnframes() / source.getframerate()
            channels, rate = source.getnchannels(), source.getframerate()
        if channels != 1 or rate != 16_000:
            raise SystemExit(f"{name}: expected 16 kHz mono, got {rate} Hz x{channels}")
        manifest.append(
            {
                "id": f"pipecat-{row['sample_id'][:8]}",
                "dataset": DATASET,
                "split": "train",
                "audio": name,
                "sha256": hashlib.sha256(audio).hexdigest(),
                "duration": round(duration, 3),
                "reference": reference,
                "accent": "voice-agent",
            }
        )

    lines = [json.dumps(entry, ensure_ascii=False) for entry in manifest]
    (args.destination / "manifest.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    seconds = sum(float(entry["duration"]) for entry in manifest)
    words = sum(len(str(entry["reference"]).split()) for entry in manifest)
    print(
        f"{len(manifest)} clips, {seconds / 60:.1f} minutes, {words} reference words, "
        f"median {sorted(float(e['duration']) for e in manifest)[len(manifest) // 2]:.2f}s"
    )


if __name__ == "__main__":
    main()
