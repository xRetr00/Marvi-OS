"""Score streaming STT predictions against a Marvi accented-English corpus."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import unicodedata
from collections import defaultdict
from pathlib import Path

NON_SPEECH = re.compile(r"<[^>]+>")
WORD = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")


def normalize(text: str) -> list[str]:
    """Apply the same conservative English WER transform to refs and hypotheses."""

    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    text = NON_SPEECH.sub(" ", text)
    return WORD.findall(text)


def edit_counts(reference: list[str], hypothesis: list[str]) -> tuple[int, int, int]:
    """Return substitution, deletion, and insertion counts."""

    rows: list[list[tuple[int, int, int, int]]] = [
        [(index, 0, 0, index) for index in range(len(hypothesis) + 1)]
    ]
    for ref_index in range(1, len(reference) + 1):
        row = [(ref_index, 0, ref_index, 0)]
        previous = rows[-1]
        for hyp_index in range(1, len(hypothesis) + 1):
            if reference[ref_index - 1] == hypothesis[hyp_index - 1]:
                row.append(previous[hyp_index - 1])
                continue
            substitution = previous[hyp_index - 1]
            deletion = previous[hyp_index]
            insertion = row[hyp_index - 1]
            choices = (
                (
                    substitution[0] + 1,
                    substitution[1] + 1,
                    substitution[2],
                    substitution[3],
                ),
                (deletion[0] + 1, deletion[1], deletion[2] + 1, deletion[3]),
                (insertion[0] + 1, insertion[1], insertion[2], insertion[3] + 1),
            )
            row.append(min(choices))
        rows.append(row)
    _, substitutions, deletions, insertions = rows[-1][-1]
    return substitutions, deletions, insertions


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = math.ceil(fraction * len(ordered)) - 1
    return round(ordered[max(0, index)], 3)


def _score_group(rows: list[dict[str, object]]) -> dict[str, object]:
    refs = sum(int(row["reference_words"]) for row in rows)
    substitutions = sum(int(row["substitutions"]) for row in rows)
    deletions = sum(int(row["deletions"]) for row in rows)
    insertions = sum(int(row["insertions"]) for row in rows)
    errors = substitutions + deletions + insertions
    return {
        "clips": len(rows),
        "reference_words": refs,
        "wer": round(errors / refs, 6) if refs else None,
        "substitutions": substitutions,
        "deletions": deletions,
        "insertions": insertions,
    }


def score(manifest_path: Path, predictions_path: Path) -> dict[str, object]:
    manifest = [
        json.loads(line)
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
    ]
    predictions = [
        json.loads(line)
        for line in predictions_path.read_text(encoding="utf-8").splitlines()
    ]
    by_id: dict[str, dict[str, object]] = {}
    for prediction in predictions:
        clip_id = str(prediction["id"])
        if clip_id in by_id:
            raise ValueError(f"duplicate prediction id: {clip_id}")
        by_id[clip_id] = prediction

    expected = {str(row["id"]) for row in manifest}
    actual = set(by_id)
    if expected != actual:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(
            f"prediction ids differ: missing={missing}, unexpected={unexpected}"
        )

    clips: list[dict[str, object]] = []
    for item in manifest:
        prediction = by_id[str(item["id"])]
        reference_words = normalize(str(item["reference"]))
        hypothesis_words = normalize(str(prediction.get("text", "")))
        substitutions, deletions, insertions = edit_counts(
            reference_words, hypothesis_words
        )
        clips.append(
            {
                **prediction,
                "id": item["id"],
                # Not every corpus has a first-language dimension. EdAcc and
                # L2-ARCTIC are built around one; the Pipecat voice-agent set
                # is not, and requiring the field turned a missing column into
                # a KeyError after the run had already been done.
                "l1": item.get("l1") or item.get("accent") or "all",
                "reference": item["reference"],
                "normalized_reference": " ".join(reference_words),
                "normalized_hypothesis": " ".join(hypothesis_words),
                "reference_words": len(reference_words),
                "substitutions": substitutions,
                "deletions": deletions,
                "insertions": insertions,
                "wer": round(
                    (substitutions + deletions + insertions) / len(reference_words), 6
                ),
            }
        )

    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for clip in clips:
        groups[str(clip["l1"])].append(clip)

    inference_seconds = [float(row["inference_seconds"]) for row in clips]
    audio_seconds = [float(row.get("audio_seconds", 0.0)) for row in clips]
    first_partial = [
        float(row["first_partial_ms"])
        for row in clips
        if row.get("first_partial_ms") is not None
    ]
    final_after_eos = [
        float(row["final_after_eos_ms"])
        for row in clips
        if row.get("final_after_eos_ms") is not None
    ]
    summary = _score_group(clips)
    summary.update(
        {
            "audio_seconds": round(sum(audio_seconds), 3),
            "inference_seconds": round(sum(inference_seconds), 3),
            "rtf": round(sum(inference_seconds) / sum(audio_seconds), 6),
            "first_partial_ms_p50": _percentile(first_partial, 0.5),
            "first_partial_ms_p90": _percentile(first_partial, 0.9),
            "final_after_eos_ms_p50": _percentile(final_after_eos, 0.5),
            "final_after_eos_ms_p90": _percentile(final_after_eos, 0.9),
            "peak_rss_mb": max(float(row.get("peak_rss_mb", 0.0)) for row in clips),
            "peak_vram_mb": max(float(row.get("peak_vram_mb", 0.0)) for row in clips),
            "empty_hypotheses": sum(
                not normalize(str(row.get("text", ""))) for row in clips
            ),
            "mean_clip_wer": round(
                statistics.fmean(float(row["wer"]) for row in clips), 6
            ),
        }
    )
    return {
        "schema": "marvi-stt-score-v1",
        "engine": predictions[0].get("engine") if predictions else None,
        "summary": summary,
        "by_l1": {name: _score_group(rows) for name, rows in sorted(groups.items())},
        "clips": clips,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = score(args.manifest, args.predictions)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
