"""Build Marvi's small, reproducible accented-English ASR benchmark corpus.

The source is the EdAcc test split: spontaneous conversations rather than read
prompts. We select six clips from each of nine first-language backgrounds from
a pinned 7,300-row selection pool by a stable hash of the dataset row id, then
reject audio outside the assistant-turn length band. Re-running against the
pinned dataset revision produces the same 54 rows and records a SHA-256 for
every converted 16 kHz mono WAV.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from collections import defaultdict
from pathlib import Path

DATASET = "edinburghcstr/edacc"
DATASET_REVISION = "d9ae7bd344f0562b766ec93ee5ce8f2f9568ce66"
SPLIT = "test"
TARGETS = (
    "Spanish",
    "Mandarin",
    "Hindi",
    "Lithuanian",
    "Jamaican English",
    "Nigerian English",
    "Kenyan English",
    "Ghanain English",  # EdAcc's published spelling.
    "Indian English",
)
SELECTION_ROW_LIMIT = 7_300
PER_GROUP = 6
MIN_WORDS = 5
MAX_WORDS = 28
MIN_SECONDS = 1.5
MAX_SECONDS = 12.0
ROWS_ENDPOINT = "https://datasets-server.huggingface.co/rows"


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?", text)


def _page(offset: int, cache: Path) -> list[dict[str, object]]:
    cached = cache / f"rows-{offset:05d}.json"
    if cached.is_file():
        return json.loads(cached.read_text(encoding="utf-8"))
    query = urllib.parse.urlencode(
        {
            "dataset": DATASET,
            "revision": DATASET_REVISION,
            "config": "default",
            "split": SPLIT,
            "offset": offset,
            "length": 100,
        }
    )
    request = urllib.request.Request(
        f"{ROWS_ENDPOINT}?{query}", headers={"User-Agent": "Marvi-OS-STT-Eval/1"}
    )
    for attempt in range(8):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                revision = response.headers.get("x-revision")
                if revision and revision != DATASET_REVISION:
                    raise RuntimeError(
                        f"EdAcc revision changed: expected {DATASET_REVISION}, got {revision}"
                    )
                rows = json.load(response)["rows"]
            cached.write_text(json.dumps(rows), encoding="utf-8")
            time.sleep(0.25)
            return rows
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 7:
                raise
            retry_after = error.headers.get("Retry-After")
            time.sleep(float(retry_after) if retry_after else 2**attempt)
    raise RuntimeError("dataset page retry loop ended unexpectedly")


def _rank(row: dict[str, object]) -> str:
    item = row["row"]
    key = f"marvi-edacc-v1:{item['l1']}:{row['row_idx']}"
    return hashlib.sha256(key.encode()).hexdigest()


def _duration(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(row: dict[str, object], output: Path) -> float:
    item = row["row"]
    source = item["audio"][0]["src"]
    request = urllib.request.Request(
        source, headers={"User-Agent": "Marvi-OS-STT-Eval/1"}
    )
    # NamedTemporaryFile remains locked on Windows, so ffmpeg must receive a
    # closed file inside a temporary directory.
    with tempfile.TemporaryDirectory(prefix="marvi-stt-") as raw_dir:
        raw_path = Path(raw_dir) / "source.wav"
        with urllib.request.urlopen(request, timeout=120) as response:
            raw_path.write_bytes(response.read())
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(raw_path),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-sample_fmt",
                "s16",
                str(output),
            ],
            check=True,
        )
    return _duration(output)


def build(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    cache = output / ".metadata" / DATASET_REVISION[:12]
    cache.mkdir(exist_ok=True)
    candidates: dict[str, list[dict[str, object]]] = defaultdict(list)
    offset = 0
    while offset < SELECTION_ROW_LIMIT:
        rows = _page(offset, cache)
        if not rows:
            break
        for row in rows:
            item = row["row"]
            text = str(item["text"])
            if item["l1"] in TARGETS and MIN_WORDS <= len(_words(text)) <= MAX_WORDS:
                candidates[str(item["l1"])].append(row)
        offset += len(rows)

    manifest = []
    for l1 in TARGETS:
        accepted = 0
        selected_rows: set[int] = set()
        speaker_counts: dict[str, int] = defaultdict(int)
        ranked = sorted(candidates[l1], key=lambda row: (_rank(row), row["row_idx"]))
        # The first pass caps a speaker at three clips. Sparse L1 groups get a
        # second pass so the corpus stays balanced by L1 rather than silently
        # dropping the hardest backgrounds.
        for speaker_cap in (3, PER_GROUP):
            for row in ranked:
                if accepted >= PER_GROUP:
                    break
                item = row["row"]
                speaker = str(item["speaker"])
                row_index = int(row["row_idx"])
                if row_index in selected_rows:
                    continue
                if speaker_counts[speaker] >= speaker_cap:
                    continue
                name = f"{l1.lower().replace(' ', '-')}-{row_index}.wav"
                path = output / name
                duration = _download(row, path)
                if not MIN_SECONDS <= duration <= MAX_SECONDS:
                    path.unlink(missing_ok=True)
                    continue
                speaker_counts[speaker] += 1
                selected_rows.add(row_index)
                accepted += 1
                manifest.append(
                    {
                        "id": f"edacc-test-{row_index}",
                        "dataset": DATASET,
                        "dataset_revision": DATASET_REVISION,
                        "split": SPLIT,
                        "row": row_index,
                        "audio": name,
                        "sha256": _sha256(path),
                        "duration": round(duration, 3),
                        "reference": str(item["text"]),
                        "speaker": speaker,
                        "gender": str(item["gender"]),
                        "accent": str(item["accent"]),
                        "l1": l1,
                    }
                )
            if accepted >= PER_GROUP:
                break
        if accepted != PER_GROUP:
            raise RuntimeError(f"selected only {accepted}/{PER_GROUP} clips for {l1}")

    manifest.sort(key=lambda item: (TARGETS.index(item["l1"]), item["row"]))
    manifest_path = output / "manifest.jsonl"
    manifest_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in manifest),
        encoding="utf-8",
    )
    print(f"wrote {len(manifest)} clips to {manifest_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.output.resolve())


if __name__ == "__main__":
    main()
