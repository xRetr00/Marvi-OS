"""Making a memory findable without changing what it says.

The failure this exists for, measured on a real store of 146 memories:

    ? what is my schedule like
      - The user uses deepseek-v4-flash for scheduled cron jobs
      - The user routes cron job output to a Telegram channel
      ...

The answer -- "works as the main dough chef at a bakery in Düzce, typically
night shifts" -- was in the store and ranked nowhere, while four memories about
*scheduled jobs* took the top. Four fixes were tried and measured against it: a
bigger bi-encoder, two cross-encoder rerankers, and MMR diversification. All
four scored the same or worse. It is not a ranking problem and no model fixes
it, because the text simply does not contain the word: "night shifts" is a
schedule and never says so.

## Why this rewrites the vector and not the memory

The obvious fix -- rewrite the memory to say "schedule" -- is the wrong one.
The body is what Marvi reads out and reasons over, it is what the user can
correct in the graph, and a model editing it in the background is a model
quietly changing what she believes. A wrong rewrite would be indistinguishable
from a wrong memory.

So the body is left exactly as written and a second line is stored beside it,
used only to compute the vector: the words somebody would use to ask for this.
`memory_search` and `recall_block` return the original sentence; only the
embedding sees the addition. Nothing Marvi says can change because of this,
which is what makes it safe to run unattended.

## What it achieved, measured

Run over the whole store: 128 of 144 memories were given their question words,
and the words are right -- the bakery memory came back as "work, job,
employment, bakery, dough chef, night shift, Düzce, schedule", which contains
exactly the term it was missing.

The score on the eight questions did **not** move. Still 7/8, still missing
"what is my schedule like".

The reason is dilution: the retrieval line is appended to the memory and the
pair is embedded as one text, so eight keywords sit alongside a sentence four
times their length and shift the vector very little. The competing memories are
genuinely about scheduled things, and a nudge is not enough to overtake them.

The fix that would work is a second vector -- embed the retrieval line on its
own and score a memory by the better of its two similarities -- so the question
words compete on their own terms instead of being averaged into the sentence.
That is a schema change and a change to `search_similar`, and it is the next
thing to do here rather than something this module already does.

## Why it is opt-in

It is a model call per memory. On a store that has just absorbed an import that
is several hundred calls, and the benefit is real but narrow -- it fixes
questions whose vocabulary the memory happens not to share. Somebody should
choose to spend that, and the Memory page is where.
"""

from __future__ import annotations

import os
import re
from typing import Any

from . import distil
from .logs import get_logger

log = get_logger("memory")

SETTING = "MARVI_MEMORY_REPHRASE"

#: How many memories one pass enriches. Bounded because each is a model call,
#: and because a pass that runs for an hour is one nobody can reason about.
BATCH = 40

#: Asked for in one call for several memories rather than one call each: the
#: work is short, the overhead is the round trip, and forty round trips to add
#: a line each is the wrong shape.
PER_CALL = 8

MAX_OUTPUT_TOKENS = 1_200

#: A line long enough to carry the words a question would use and short enough
#: that it does not drown the memory it belongs to when both are embedded.
MAX_LINE = 240

SYSTEM_PROMPT = (
    "For each memory, write the words somebody would use to ask about it.\n"
    "\n"
    "Reply with one JSON object and nothing else:\n"
    '{"asked":[{"id":<id>,"words":"..."}]}\n'
    "\n"
    "This is not a summary and not a rewrite. The memory stays exactly as it "
    "is; you are adding the vocabulary a search would arrive with, because a "
    "memory is written as a statement and looked for as a question.\n"
    "\n"
    "Worked example. The memory:\n"
    "  The user works as the main dough chef at a bakery, typically night "
    "shifts.\n"
    "would be asked for as:\n"
    "  working schedule, working hours, shift pattern, what time they work, "
    "night work, day job, employment, where they work\n"
    "\n"
    "Rules:\n"
    "- Name the *category* the memory belongs to, which is usually the word "
    "the memory itself is missing: schedule, diet, health, budget, hardware, "
    "family, travel, sleep, money, education.\n"
    "- Include the plain-English question forms: 'what do I do for work', "
    "'where do I live'.\n"
    "- Only what the memory actually supports. Adding words for things it does "
    "not say makes it answer questions it cannot answer, which is worse than "
    "not being found.\n"
    "- One line per memory, no more than thirty words.\n"
    "- Skip a memory that is already stated in the words it would be asked for; "
    "return it with an empty string."
)


def enabled() -> bool:
    return os.environ.get(SETTING, "").strip().lower() in ("1", "true", "yes", "on")


def _parse(text: str) -> dict[int, str]:
    """`{memory id: words}` from a model's reply. Never raises."""
    import json

    body = (text or "").strip().strip("`")
    if body.lower().startswith("json"):
        body = body[4:].strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        parsed = json.loads(body[start : end + 1])
    except ValueError:
        return {}
    found: dict[int, str] = {}
    for row in (parsed.get("asked") or []) if isinstance(parsed, dict) else []:
        if not isinstance(row, dict):
            continue
        try:
            memory_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        words = re.sub(r"\s+", " ", str(row.get("words") or "")).strip()
        found[memory_id] = words[:MAX_LINE]
    return found


def describe(client: Any, memories: list[dict[str, Any]]) -> dict[int, str]:
    """The words each of these would be asked for. `{}` when nothing is usable."""
    if client is None or not memories:
        return {}
    listed = "\n".join(
        f'[{row["id"]}] {row["subject"]}: {str(row["body"])[:300]}' for row in memories
    )
    try:
        answer = distil.ask(
            client, "memory", SYSTEM_PROMPT, listed, MAX_OUTPUT_TOKENS, tools=False
        )
    except Exception as exc:
        log.info("rephrasing unavailable (%s); nothing enriched", exc)
        return {}
    known = {int(row["id"]) for row in memories}
    return {
        memory_id: words
        for memory_id, words in _parse(answer).items()
        if memory_id in known and words
    }


def run(store: Any, client: Any, limit: int = BATCH) -> dict[str, int]:
    """Give unenriched memories the words they would be asked for.

    Returns what changed. Never raises: this runs on the scheduler's thread
    beside the other background passes, and one that dies takes them with it.
    """
    if not enabled():
        return {"considered": 0, "enriched": 0}
    try:
        pending = store.without_retrieval(limit=limit)
    except Exception as exc:  # pragma: no cover - depends on the store
        log.warning("could not read what needs rephrasing: %s", exc)
        return {"considered": 0, "enriched": 0}
    if not pending:
        return {"considered": 0, "enriched": 0}

    enriched = 0
    for start in range(0, len(pending), PER_CALL):
        batch = pending[start : start + PER_CALL]
        for memory_id, words in describe(client, batch).items():
            try:
                store.set_retrieval(memory_id, words)
                enriched += 1
            except Exception as exc:
                log.warning("could not store the retrieval line for %s: %s", memory_id, exc)
    if enriched:
        log.info(
            "memory: %d entries given the words they would be asked for",
            enriched,
            extra={"marvi_considered": len(pending)},
        )
    return {"considered": len(pending), "enriched": enriched}
