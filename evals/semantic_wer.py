"""Semantic WER: count the errors that change what was said.

Every STT number in `docs/evals` so far is raw WER, which counts every token
difference the same. That is the wrong scoreboard for Marvi, and the three
rounds already recorded quietly show it: an engine that writes "gonna" where
the reference says "going to" is charged two errors, and an engine that writes
"deploy the staging branch" where the reference says "destroy the staging
branch" is charged one. The second mistake is the one that gets somebody paged.

Pipecat's benchmark scores this the other way round -- ignore punctuation,
capitalisation, contractions, filler words and number formatting; count
substitutions that change meaning, invented words, and dropped words that
change intent. This implements that, so our engines can be read on the same
axis as their published table.

## Why an LLM and not a normaliser

A normaliser gets most of the formatting cases and none of the meaning ones.
"Fifty" versus "15" is a formatting difference by string distance and a
meaning difference in a calendar. The judgement is the metric, so the judge has
to understand the sentence.

Raw WER is still computed and still reported. This does not replace
`stt_score.py`; it adds the column that answers a different question, and where
the two disagree the disagreement is the finding.

## Reading the output

`semantic_wer` is meaning-changing errors over reference words, pooled -- the
same denominator as the raw figure, so the two are directly comparable.
`clean_rate` is the share of clips with no meaning-changing error at all, which
is the number that predicts how a conversation feels: one bad clip in ten is a
different assistant from one in fifty, and both can average 12%.

    python evals/semantic_wer.py <manifest.jsonl> <predictions.jsonl> --output x.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

#: A model that is cheap enough for a thousand judgements and good enough to
#: tell "destroy" from "deploy". The judgement is the metric; a model that
#: cannot read a sentence makes the whole column noise.
JUDGE = "anthropic/claude-sonnet-4.5"

WHERE = "https://openrouter.ai/api/v1/chat/completions"

#: Judgements in flight. The bound is politeness, not throughput.
AT_ONCE = 8

ATTEMPTS = 3

PROMPT = """You are scoring a speech recogniser against a reference transcript.

Count only errors that change what was said. Ignore differences in punctuation,
capitalisation, contractions ("going to"/"gonna"), filler words ("uh", "um"),
disfluency, and number or date formatting ("15"/"fifteen", "3pm"/"three p.m.").

Count as errors:
- a word replaced by one that changes the meaning
- an invented or nonsense word that is not in the reference
- a missing word that changes the intent of the sentence
- an added word that changes the intent of the sentence

REFERENCE:
{reference}

HYPOTHESIS:
{hypothesis}

Reply with one line of JSON and nothing else:
{{"errors": <integer>, "why": "<at most twelve words, or empty when zero>"}}"""


def _key() -> str:
    """The OpenRouter key, from the environment or Marvi's provider file."""
    if found := os.environ.get("OPENROUTER_API_KEY"):
        return found
    where = Path(os.environ.get("LOCALAPPDATA", "")) / "Marvi-OS" / "providers.env"
    if where.is_file():
        for line in where.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "OPENROUTER_API_KEY":
                return value.strip().strip('"')
    raise SystemExit("no OPENROUTER_API_KEY in the environment or providers.env")


def judge(key: str, reference: str, hypothesis: str) -> tuple[int, str]:
    """Meaning-changing errors in one hypothesis, and a short why."""
    import httpx

    if not hypothesis.strip():
        # An empty hypothesis is every reference word missing, and asking a
        # model to confirm that is a request that can only go wrong.
        return len(reference.split()), "nothing transcribed"
    body = {
        "model": JUDGE,
        "messages": [
            {
                "role": "user",
                "content": PROMPT.format(reference=reference, hypothesis=hypothesis),
            }
        ],
        "temperature": 0,
        "max_tokens": 120,
    }
    last = ""
    for attempt in range(ATTEMPTS):
        try:
            answer = httpx.post(
                WHERE,
                json=body,
                headers={"Authorization": f"Bearer {key}"},
                timeout=90.0,
            )
            answer.raise_for_status()
            said = answer.json()["choices"][0]["message"]["content"]
            found = re.search(r"\{.*\}", said, re.DOTALL)
            if not found:
                last = f"unparsable: {said[:60]}"
                continue
            parsed = json.loads(found.group(0))
            return max(0, int(parsed["errors"])), str(parsed.get("why") or "")
        except Exception as exc:  # noqa: BLE001 - one clip failing must not end the run
            last = str(exc)[:120]
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"judge failed: {last}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    references = {
        row["id"]: row["reference"]
        for row in (
            json.loads(line)
            for line in args.manifest.read_text(encoding="utf-8").splitlines()
        )
    }
    predictions = [
        json.loads(line)
        for line in args.predictions.read_text(encoding="utf-8").splitlines()
    ]
    if args.limit:
        predictions = predictions[: args.limit]
    key = _key()

    def score(row: dict) -> dict:
        reference = references[row["id"]]
        errors, why = judge(key, reference, str(row.get("text") or ""))
        return {
            "id": row["id"],
            "words": len(reference.split()),
            "errors": errors,
            "why": why,
            "text": row.get("text"),
        }

    with ThreadPoolExecutor(max_workers=AT_ONCE) as pool:
        judged = list(pool.map(score, predictions))

    words = sum(row["words"] for row in judged)
    errors = sum(row["errors"] for row in judged)
    clean = sum(1 for row in judged if row["errors"] == 0)
    summary = {
        "clips": len(judged),
        "reference_words": words,
        "meaning_errors": errors,
        "semantic_wer": round(errors / words, 6) if words else 0.0,
        "clean_clips": clean,
        "clean_rate": round(clean / len(judged), 6) if judged else 0.0,
        "judge": JUDGE,
    }
    args.output.write_text(
        json.dumps({"summary": summary, "clips": judged}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
