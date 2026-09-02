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

#: Clips per first-language group. Was six, which put 53-95 reference words in
#: each group and about 680 in the whole corpus -- so a bootstrap over the
#: clips gave Nemotron [23.78, 36.70] and Whisper [29.69, 44.44], intervals
#: that overlap almost entirely. The first round ranked those two, and one
#: other, as though the order meant something.
#:
#: Eighteen roughly triples the words and halves the interval width. It does
#: not make six clips per group into a language benchmark; it makes the
#: aggregate ranking say something.
PER_GROUP = 18

#: L2-ARCTIC, for the accents EdAcc does not carry. Arabic-accented English is
#: the one that matters most here and EdAcc has no Arabic L1 group at all, so
#: the first round could not measure it.
#:
#: Kept as a separate slice and never pooled into one WER with EdAcc. These are
#: read CMU ARCTIC prompts and EdAcc is spontaneous conversation: read speech
#: scores far better, and averaging the two lets an engine that is good at
#: prompts hide behind a number that claims to be about talking.
L2_DATASET = "KoelLabs/L2Arctic"
#: `scripted`, not `spontaneous`, and the reason is length rather than
#: preference. The spontaneous config is 22 "suitcase" recordings of about
#: seventy seconds each; every one of them falls outside the 1.5-12 second
#: assistant-turn band this corpus selects for, so the slice would be empty.
#: The scripted config is CMU ARCTIC prompts -- short sentences, the right
#: length, and read rather than spoken.
#:
#: Which is why it is reported on its own and never pooled with EdAcc. Read
#: speech scores far better than conversation, and one number covering both
#: lets an engine that is good at prompts hide behind a figure that claims to
#: be about talking.
L2_SPLIT = "scripted"

#: How many clips per L1 group in the L2-ARCTIC slice. Arabic is the reason
#: this source is here, so it gets more depth than an EdAcc group rather
#: than a token handful: eighteen clips came to 180 reference words, which
#: is a +/-10 point confidence interval and not worth reporting. L2-ARCTIC
#: has about 900 utterances per speaker, so the words are there for the
#: asking -- the only limit is that Arabic has four speakers.
L2_PER_GROUP = 48

#: L2-ARCTIC's own L1 labels. Arabic first because it is the reason this
#: source is here.
L2_TARGETS = ("Arabic", "Mandarin", "Hindi", "Korean", "Spanish", "Vietnamese")
MIN_WORDS = 5
MAX_WORDS = 28
MIN_SECONDS = 1.5
MAX_SECONDS = 12.0
ROWS_ENDPOINT = "https://datasets-server.huggingface.co/rows"

#: L2-ARCTIC is gated on both public mirrors: the rows endpoint answers 401
#: without a token, and the token only works once the dataset's terms have been
#: accepted on its Hugging Face page. EdAcc needs neither, which is why the
#: first round used it alone.
TOKEN_SETTING = "HF_TOKEN"


def _token() -> str:
    import os

    return os.environ.get(TOKEN_SETTING, "").strip()


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?", text)


def _page(offset: int, cache: Path) -> list[dict[str, object]]:
    return _rows(DATASET, SPLIT, offset, cache, revision=DATASET_REVISION)


def _rows(
    dataset: str, split: str, offset: int, cache: Path, revision: str = ""
) -> list[dict[str, object]]:
    """One page of a dataset's rows, cached and rate-limit aware.

    Shared by both sources. L2-ARCTIC is gated, so it needs the token below and
    the dataset's terms accepted on its Hugging Face page; EdAcc needs neither,
    which is why the first round used it alone.
    """
    cached = cache / f"rows-{offset:05d}.json"
    if cached.is_file():
        return json.loads(cached.read_text(encoding="utf-8"))
    fields: dict[str, object] = {
        "dataset": dataset,
        "config": "default",
        "split": split,
        "offset": offset,
        "length": 100,
    }
    if revision:
        fields["revision"] = revision
    headers = {"User-Agent": "Marvi-OS-STT-Eval/1"}
    if token := _token():
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{ROWS_ENDPOINT}?{urllib.parse.urlencode(fields)}", headers=headers
    )
    for attempt in range(8):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                seen = response.headers.get("x-revision")
                if revision and seen and seen != revision:
                    raise RuntimeError(
                        f"{dataset} revision changed: expected {revision}, got {seen}"
                    )
                rows = json.load(response)["rows"]
            cached.write_text(json.dumps(rows), encoding="utf-8")
            time.sleep(0.25)
            return rows
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                # Said plainly, because the fix is not in this file. Both public
                # mirrors of L2-ARCTIC are gated: the terms have to be accepted
                # on the dataset's own page, and the token has to be this
                # account's.
                raise RuntimeError(
                    f"{dataset} is gated ({error.code}). Accept its terms at "
                    f"https://huggingface.co/datasets/{dataset} and set "
                    f"{TOKEN_SETTING} to a token for that account."
                ) from error
            if error.code != 429 or attempt == 7:
                raise
            retry_after = error.headers.get("Retry-After")
            time.sleep(float(retry_after) if retry_after else 2**attempt)
    raise RuntimeError("dataset page retry loop ended unexpectedly")


def _rank(row: dict[str, object], namespace: str = "marvi-edacc-v1") -> str:
    """A stable order over a source's rows, so a rebuild picks the same clips.

    The group name is part of the key, and L2-ARCTIC calls it
    `speaker_native_language` where EdAcc calls it `l1` -- reading only the
    EdAcc name raised `KeyError: 'l1'` on the first L2 build.
    """
    item = row["row"]
    group = item.get("l1") or item.get("speaker_native_language") or ""
    key = f"{namespace}:{group}:{row['row_idx']}"
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
    # `parents`, because the `.metadata` directory above it is new too.
    cache.mkdir(parents=True, exist_ok=True)
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


def build_l2(output: Path, only: tuple[str, ...] = L2_TARGETS) -> None:
    """The L2-ARCTIC slice: accents EdAcc does not carry, Arabic above all.

    EdAcc has no Arabic L1 group at all, so the first round could not measure
    the accent that matters most here. This is that slice, written to its own
    manifest so it is scored and reported separately.
    """
    output.mkdir(parents=True, exist_ok=True)
    cache = output / ".metadata" / "l2arctic"
    cache.mkdir(parents=True, exist_ok=True)

    candidates: dict[str, list[dict[str, object]]] = defaultdict(list)
    offset = 0
    while offset < SELECTION_ROW_LIMIT:
        rows = _rows(L2_DATASET, L2_SPLIT, offset, cache)
        if not rows:
            break
        for row in rows:
            item = row["row"]
            language = str(item.get("speaker_native_language") or "")
            text = str(item.get("text") or "")
            if language in only and MIN_WORDS <= len(_words(text)) <= MAX_WORDS:
                candidates[language].append(row)
        offset += len(rows)

    manifest = []
    for language in only:
        accepted = 0
        speakers: dict[str, int] = defaultdict(int)
        # The second pass revisits rows the first already took, so without this
        # a relaxed cap re-adds them and the manifest carries the same clip
        # twice -- which the scorer refuses outright: "duplicate prediction id".
        taken: set[int] = set()
        ranked = sorted(
            candidates[language],
            key=lambda row: (_rank(row, "marvi-l2arctic-v1"), row["row_idx"]),
        )
        # The same two-pass speaker cap EdAcc uses: three per speaker first, so
        # a group is not one person read eighteen times, then relaxed rather
        # than dropping a background for being thin.
        for cap in (3, L2_PER_GROUP):
            for row in ranked:
                if accepted >= L2_PER_GROUP:
                    break
                item = row["row"]
                speaker = str(item.get("speaker_code") or "")
                if speakers[speaker] >= cap:
                    continue
                index = int(row["row_idx"])
                if index in taken:
                    continue
                name = f"l2-{language.lower()}-{index}.wav"
                path = output / name
                # Reused, not skipped. `continue` here meant a rebuild dropped
                # every clip it had already downloaded instead of counting it,
                # so growing the slice would have silently shrunk it.
                duration = _duration(path) if path.is_file() else _download(row, path)
                if not MIN_SECONDS <= duration <= MAX_SECONDS:
                    path.unlink(missing_ok=True)
                    continue
                speakers[speaker] += 1
                taken.add(index)
                accepted += 1
                manifest.append(
                    {
                        "id": f"l2arctic-{L2_SPLIT}-{index}",
                        "dataset": L2_DATASET,
                        "split": L2_SPLIT,
                        "row": index,
                        "audio": name,
                        "sha256": _sha256(path),
                        "duration": round(duration, 3),
                        "reference": str(item.get("text") or ""),
                        "speaker": speaker,
                        "gender": str(item.get("speaker_gender") or ""),
                        "accent": language,
                        "l1": language,
                    }
                )
            if accepted >= L2_PER_GROUP:
                break
        print(f"{language}: {accepted} clips", flush=True)

    manifest.sort(key=lambda item: (str(item["l1"]), int(item["row"])))
    manifest_path = output / "manifest.jsonl"
    manifest_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in manifest),
        encoding="utf-8",
    )
    print(f"wrote {len(manifest)} clips to {manifest_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--l2",
        action="store_true",
        help="build the L2-ARCTIC slice instead of the EdAcc one (needs HF_TOKEN)",
    )
    parser.add_argument(
        "--l1",
        action="append",
        help="restrict the L2 slice to these first languages, e.g. --l1 Arabic",
    )
    args = parser.parse_args()
    if args.l2:
        build_l2(args.output.resolve(), tuple(args.l1) if args.l1 else L2_TARGETS)
    else:
        build(args.output.resolve())


if __name__ == "__main__":
    main()
