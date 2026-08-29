"""Does memory need a model to read it, or only to write it?

Marvi's memory has four LLM passes on the **write** side -- extraction after a
turn, skill learning, dreaming, rephrasing -- and **none** on the read side.
`recall_block` runs a hybrid search and hands the top few memories to the voice
model as prompt text. Honcho's Dialectic API is the shape this is missing: a
model that *answers the question from memory* rather than returning the rows
nearest to it.

This measures whether that second half is worth building, against the real
store, on questions whose answers are known to be in it.

    python evals/memory_answers.py                  # all conditions
    python evals/memory_answers.py --runs 3 --model qwen/qwen3.7-flash

## The hypothesis worth testing

Retrieval already finds the answer more often than it ranks it first. Measured
earlier on this store: asked "what do I do for work", the correct memory (the
bakery) came back **fourth at 0.550**, below three wrong ones scoring higher.
Search-only hands all five to the voice model and hopes it picks correctly
while also holding a conversation.

If that is the real failure, then a reader model changes the score and a better
ranker does not -- and four ranking changes have already been measured on this
store and moved nothing (bigger bi-encoder, two cross-encoders, MMR).

## Conditions

`search_top1`   Is the answer in the single best-ranked memory? This is what a
                perfect ranker would need to achieve.

`search_top5`   Is the answer anywhere in what recall actually sends? This is
                the ceiling a reader model could reach without better search.

`read_5`        A model is given the same five and asked the question. This is
                Honcho's Dialectic shape at Marvi's current recall width.

`read_10`       The same, given ten. Tests whether the reader benefits from
                seeing more than recall currently sends -- a reader can afford
                width that a voice prompt cannot.

## Abstention is scored separately and matters as much

Two of the questions have **no answer in the store**. Marvi's worst memory
failures were not wrong retrievals, they were confident answers built from
whatever came back: asked about a schedule she answered from cron jobs, and
asked what she remembered she invented six memories that do not exist.

A reader that answers everything is not an improvement. `abstains` counts the
unanswerable questions where the model said so.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import statistics
import sys
import time
from dataclasses import dataclass, field

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "services/gateway/src"))

STORE = pathlib.Path("C:/Users/xRetro/AppData/Local/Marvi-OS/memory.sqlite3")

READER_PROMPT = (
    "Answer the question using only the memories below. They are notes about "
    "one person, retrieved by a search that is often wrong about which ones "
    "matter -- the answer may be the fourth of five, or absent entirely.\n\n"
    "If the memories do not contain the answer, reply exactly: NOT IN MEMORY\n"
    "Never guess from the nearest one. Otherwise answer in one short sentence."
)


@dataclass(frozen=True)
class Question:
    asked: str
    #: Any of these in the answer means it is right. Drawn from the real
    #: memory that holds it, so a paraphrase still counts.
    expect: tuple[str, ...] = ()
    #: True when the store genuinely cannot answer, and saying so is the win.
    unanswerable: bool = False


QUESTIONS = [
    Question("what do I do for work", ("bakery", "dough")),
    Question("what computer do I have", ("3060", "ryzen")),
    Question("where do I live", ("düzce", "duzce", "türkiye", "turkey")),
    Question("what am I building", ("neudocs", "marvi")),
    Question("what games do I play", ("fc 26", "ea sports", "football")),
    Question("what food do I dislike", ("insect",)),
    Question("what language do I prefer replies in", ("arabic",)),
    Question("who am I", ("shereef", "shreef", "sharif", "xretro", "egyptian")),
    # Nothing in the store answers these. Saying so is the correct behaviour.
    Question("what did I eat for breakfast today", unanswerable=True),
    Question("what is my sister's name", unanswerable=True),
]


@dataclass
class Score:
    label: str
    right: int = 0
    wrong: int = 0
    abstained: int = 0
    false_abstain: int = 0
    latency: list[float] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    misses: list[str] = field(default_factory=list)

    @property
    def answerable(self) -> int:
        return self.right + self.wrong + self.false_abstain


def hit(text: str, question: Question) -> bool:
    low = text.lower()
    return any(word in low for word in question.expect)


def ask_reader(key: str, model: str, question: Question, memories: list[str]) -> tuple[str, float, dict]:
    listed = "\n".join(f"- {line}" for line in memories)
    started = time.monotonic()
    response = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"authorization": f"Bearer {key}", "content-type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": READER_PROMPT},
                {"role": "user", "content": f"Memories:\n{listed}\n\nQuestion: {question.asked}"},
            ],
            "max_tokens": 120,
            "reasoning": {"enabled": False, "exclude": True},
        },
        timeout=90,
    )
    elapsed = time.monotonic() - started
    response.raise_for_status()
    payload = response.json()
    usage = payload.get("usage") or {}
    return (
        (payload["choices"][0]["message"].get("content") or "").strip(),
        elapsed,
        {"in": int(usage.get("prompt_tokens") or 0), "out": int(usage.get("completion_tokens") or 0)},
    )


def run(store, key: str, model: str, runs: int) -> list[Score]:
    search_1 = Score("search_top1")
    search_5 = Score("search_top5")
    read_5 = Score("read_5")
    read_10 = Score("read_10")

    for question in QUESTIONS:
        started = time.monotonic()
        found = store.search(question.asked, limit=10)
        retrieval = time.monotonic() - started
        lines = [f"{row['subject']}: {row['body']}" for row in found]

        # -- search only, no model ------------------------------------------
        for score, window in ((search_1, lines[:1]), (search_5, lines[:5])):
            score.latency.append(retrieval)
            joined = " ".join(window)
            if question.unanswerable:
                # Search cannot abstain. It returns rows whatever was asked,
                # which is the whole problem: the voice model is then handed
                # five confident-looking lines about something else.
                score.wrong += 1
                continue
            if hit(joined, question):
                score.right += 1
            else:
                score.wrong += 1
                score.misses.append(question.asked)

        # -- a model reading the same memories -------------------------------
        for score, window in ((read_5, lines[:5]), (read_10, lines[:10])):
            for _ in range(runs):
                try:
                    said, elapsed, usage = ask_reader(key, model, question, window)
                except Exception as exc:  # noqa: BLE001 - a provider error is not a result
                    score.misses.append(f"[error] {str(exc)[:50]}")
                    continue
                score.latency.append(elapsed + retrieval)
                score.tokens_in += usage["in"]
                score.tokens_out += usage["out"]
                abstained = "not in memory" in said.lower()
                if question.unanswerable:
                    if abstained:
                        score.abstained += 1
                    else:
                        score.wrong += 1
                        score.misses.append(f"{question.asked} -> {said[:60]}")
                elif abstained:
                    score.false_abstain += 1
                    score.misses.append(f"{question.asked} -> refused, answer was there")
                elif hit(said, question):
                    score.right += 1
                else:
                    score.wrong += 1
                    score.misses.append(f"{question.asked} -> {said[:60]}")

    return [search_1, search_5, read_5, read_10]


def report(scores: list[Score], runs: int, price: tuple[float, float]) -> None:
    answerable = sum(1 for q in QUESTIONS if not q.unanswerable)
    blind = len(QUESTIONS) - answerable
    print("\n" + "=" * 92)
    print(
        f"{'condition':<14} {'answered right':>15} {'abstained':>12} "
        f"{'median':>9} {'$/1k recalls':>13}"
    )
    print(f"{'':14} {'of ' + str(answerable) + ' answerable':>15} {'of ' + str(blind):>12}")
    print("-" * 92)
    for score in scores:
        per_question = max(1, score.answerable // max(1, answerable))
        right = score.right / per_question
        abstain = score.abstained / max(1, runs) if score.label.startswith("read") else 0
        median = statistics.median(score.latency) if score.latency else float("nan")
        calls = max(1, len(score.latency))
        cost = ((score.tokens_in / calls) * price[0] + (score.tokens_out / calls) * price[1]) * 1000
        print(
            f"{score.label:<14} {right:>13.1f}/{answerable} {abstain:>10.1f}/{blind} "
            f"{median * 1000:>8.0f}ms {cost:>13.2f}"
        )
    print("\nwhat each condition got wrong:")
    for score in scores:
        for miss in dict.fromkeys(score.misses):
            print(f"  {score.label:<14} {miss}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen/qwen3.7-flash")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--store", default=str(STORE))
    args = parser.parse_args()

    from marvi_gateway.memory import MemoryStore
    from marvi_gateway.providers import config as provider_config

    for name, value in provider_config.read().items():
        os.environ.setdefault(name, value)

    # A copy, because a measurement must not change what it measures.
    import shutil
    import tempfile

    work = pathlib.Path(tempfile.mkdtemp()) / "memory.sqlite3"
    shutil.copy(args.store, work)
    store = MemoryStore(work)
    store.warm()
    print(f"{store.count()} memories, reader = {args.model}, {args.runs} runs per question")

    catalogue = httpx.get("https://openrouter.ai/api/v1/models", timeout=30).json()["data"]
    price = next(
        (
            (float(m["pricing"]["prompt"]), float(m["pricing"]["completion"]))
            for m in catalogue
            if m["id"] == args.model
        ),
        (0.0, 0.0),
    )

    scores = run(store, os.environ["OPENROUTER_API_KEY"], args.model, args.runs)
    report(scores, args.runs, price)
    print("\n" + json.dumps({s.label: {"right": s.right, "wrong": s.wrong,
                                       "abstained": s.abstained,
                                       "false_abstain": s.false_abstain} for s in scores}))


if __name__ == "__main__":
    main()
