"""A model that answers from memory, instead of handing over the search results.

Marvi's memory has four model passes on the **write** side -- extraction after
a turn, skill learning, dreaming, rephrasing -- and none on the read side.
`recall_block` runs a hybrid search and puts the top few memories in front of
the voice model as prompt text, which then has to work out which of them bears
on the question while also holding a conversation.

Honcho's Dialectic API is the shape that was missing, and `evals/memory_answers.py`
measured whether it is worth having. Against the real store of 153 memories,
eight questions it can answer and two it cannot:

    condition       right of 8    abstained of 2    median
    search_top1        4             0                30ms
    search_top5        8             0                30ms
    read_5             8             2               635ms

Three things follow from that table, and they decide the whole design.

**Retrieval is not the problem.** Every answerable question had its answer
inside the top five. Nothing needs a better embedder, a vector database or an
index; the search already finds it.

**Ranking is bad and it does not matter.** Top-1 was right half the time --
asked "what do I do for work", the bakery memory came back fourth at 0.550,
below three wrong ones. A reranker would fix that number, and four ranking
changes have already been measured on this store and moved nothing. The reader
makes the ranking irrelevant instead: it reads all five.

**The thing search cannot do at all is say "I do not know".** Search returns
five rows whatever it is asked. That is the root of every confabulation in the
logs: asked about a schedule with nothing in the store about one, Marvi was
handed five confident-looking lines about cron jobs and answered from them. The
reader abstained on both unanswerable questions, twice each.

## Why this does not cost a turn

The reader takes ~600ms, and the voice path already fetches recall
speculatively while the user is still speaking (`session._Prefetch`). Measured
over 121 real turns, the window between the first partial transcript and the
end of the turn is 1,789ms at the median and 1,082ms at the lower quartile --
**a 635ms reader fits inside 98% of them**. It is paid in time that was being
spent anyway.

The 2% that do not fit need no timeout, because of where this is asked from.
Only the *speculative* fetch requests a reading; the live fallback -- the one
that runs when the prefetch missed, on the critical path -- asks for the plain
memory list as before. So a reader that is too slow simply does not arrive in
time to be used, and the turn is exactly as fast as it was without one. Nothing
waits for this.
"""

from __future__ import annotations

import os
from typing import Any

from . import distil
from .logs import get_logger

log = get_logger("memory")

SETTING = "MARVI_MEMORY_READER"

#: How many memories the reader sees. Wider than recall sends to the model,
#: because the reader can afford width a spoken prompt cannot -- and the
#: measurement found the answer inside the top five every time, so this is
#: headroom rather than a requirement.
WIDTH = 8

MAX_OUTPUT_TOKENS = 160

#: What the reader says when the memories do not answer the question. Matched
#: exactly, so a model that hedges in prose is treated as having answered.
NOTHING = "NOT IN MEMORY"

SYSTEM_PROMPT = (
    "Answer the question using only the memories below. They are notes about "
    "one person, retrieved by a search that is often wrong about which ones "
    "matter -- the answer may be the fourth of five, or absent entirely.\n"
    "\n"
    f"If the memories do not contain the answer, reply exactly: {NOTHING}\n"
    "Never guess from the nearest one. Otherwise answer in one short sentence, "
    "as a statement of what is known about the person."
)


def enabled() -> bool:
    """On unless switched off.

    Opposite of the other model passes in this package, which are opt-in
    because they cost something on a schedule. This one is paid inside a
    window that is otherwise spent waiting, and what it prevents -- answering
    a question from the nearest unrelated memory -- is the failure the owner
    reported most.
    """
    return os.environ.get(SETTING, "on").strip().lower() not in ("0", "false", "no", "off")


def answer(client: Any, question: str, memories: list[dict[str, Any]]) -> str:
    """What memory says about this, or "" to fall back to the list.

    Never raises. A reader that fails must cost the turn nothing more than the
    reader it did not get.
    """
    if client is None or not memories or not question.strip():
        return ""
    listed = "\n".join(
        f"- {row.get('subject') or 'note'}: {str(row.get('body') or '')[:300]}"
        for row in memories[:WIDTH]
    )
    try:
        said = distil.ask(
            client,
            "memory",
            SYSTEM_PROMPT,
            f"Memories:\n{listed}\n\nQuestion: {question.strip()[:400]}",
            MAX_OUTPUT_TOKENS,
            tools=False,
        )
    except Exception as exc:
        log.info("memory reader unavailable (%s); using the list", exc)
        return ""
    said = (said or "").strip()
    if not said or NOTHING.lower() in said.lower():
        return NOTHING
    return said


def block(client: Any, question: str, memories: list[dict[str, Any]]) -> str:
    """The reader's answer as prompt text, or "" when it has nothing to add.

    Deliberately not a replacement for the memory list. The list is what lets
    Marvi be corrected -- "no, the other one" needs the other one to be
    visible -- so the answer is added above it as the thing she has worked out,
    and the memories stay underneath as what she worked it out from.
    """
    if not enabled():
        return ""
    said = answer(client, question, memories)
    if not said:
        return ""
    if said == NOTHING:
        # Worth saying out loud in the prompt. The alternative is silence,
        # which reads as "no memory was consulted" rather than "memory was
        # consulted and does not know", and those produce different answers.
        return (
            "# What you remember\n\nYou have looked, and nothing you remember "
            "answers this. Say so plainly if it is what was asked about, and "
            "do not assemble an answer from anything below."
        )
    return f"# What you remember\n\n{said}"
