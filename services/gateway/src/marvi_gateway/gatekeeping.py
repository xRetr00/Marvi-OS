"""What reaches memory from outside a conversation, decided by a model.

Memory has a model on the way in from a *turn* (`remembering`) and a model on
the way out (`reading`). Everything else wrote straight into the store: a
connector's ingest, and the `memory_remember` tool a voice agent calls. Both
of those doors caused damage.

The ingest one is documented in the store itself. Hours after a mailbox was
connected, Marvi's long-term memory held "GLM-5.3-Flash is 50% off for two
weeks", "Weekly update: ETF demand and inflation pressure" and "Intuit
Developer News: August 2026" -- verbatim, JSON bodies and tracking whitespace
included -- and the graph had grown entities for A101 Ekstra, Ziraat Bankasi
and Hume Health. An inbox was being remembered as though it were a life.

The first fix was a regex: sender local-parts that mean "broadcast", plus
"unsubscribe" in the body. It works, and it is the wrong shape. It cannot tell
a newsletter from a letter that happens to say unsubscribe, it needs a new
pattern for every provider, and it can only ever answer a question about the
*envelope* when the real question is whether there is anything here about the
person.

So the same model that decides what to keep from a conversation decides what
to keep from a connector.

## Why a batch and not an item

A poll can return twenty emails. Twenty calls is twenty round trips and twenty
chances to fail; one call sees them together, which is also how a person
triages an inbox -- the newsletter is obvious *because* the letter from a human
is sitting next to it.

## Why this fails open

If the model is unavailable, everything is kept. The alternative is a
connector that silently stops remembering when a provider is down, which is
the failure this whole file exists to prevent -- something that looks like it
is working and is not. A store with some newsletters in it can be cleaned; a
week of missing correspondence cannot be recovered.
"""

from __future__ import annotations

import dataclasses
import json
import re
from typing import Any

from . import distil, observations, prompts
from .logs import get_logger

log = get_logger("memory")

#: How many items one call judges. Large enough that a poll is usually one
#: call, small enough that the prompt stays readable to the model.
BATCH = 20

MAX_OUTPUT_TOKENS = 400

#: How much of each item the judge sees. A marketing email announces itself in
#: the first line; so does a letter from a person.
PREVIEW = 400

SYSTEM_PROMPT = prompts.text("gatekeeping")


#: The longest a spoken summary may be. A model told "fifteen words" will
#: sometimes write forty, and this one gets read out.
MAX_SAYS = 160


def _parse(text: str, total: int) -> dict[int, str]:
    """Index -> what it says, from a model's reply. Never raises.

    Accepts the older bare-index shape (`{"keep":[0,3]}`) as well, because a
    model asked for JSON will occasionally hand you last week's JSON.
    """
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
    kept = parsed.get("keep") if isinstance(parsed, dict) else None
    if not isinstance(kept, list):
        return {}
    found: dict[int, str] = {}
    for entry in kept:
        if isinstance(entry, (int, float)):
            index, says = int(entry), ""
        elif isinstance(entry, dict):
            raw = entry.get("i", entry.get("index"))
            if not isinstance(raw, (int, float)):
                continue
            index, says = int(raw), str(entry.get("says") or "")[:MAX_SAYS]
        else:
            continue
        if 0 <= index < total:
            found[index] = " ".join(says.split())
    return found


#: Characters marketing mail pads its body with, hundreds at a time.
#:
#: `\s` does not match any of them -- U+034F is a combining mark, the rest are
#: format characters -- so collapsing whitespace alone left them in place, and
#: they were most of what the judge would have read. A test caught it; the eye
#: cannot, because they render as nothing.
INVISIBLE = re.compile(r"[͏​-‏⁠﻿­]+")


def _summarise(item: Any) -> str:
    """One line describing an item, for the judge to read."""
    subject = str(getattr(item, "subject", "") or "")
    body = INVISIBLE.sub("", str(getattr(item, "body", "") or ""))
    body = re.sub(r"\s+", " ", body).strip()
    return f"{subject} | {body}"[:PREVIEW]


@dataclasses.dataclass(frozen=True)
class _Item:
    """Just enough of a `MemoryItem` for `_summarise` to read."""

    subject: str
    body: str


def what_it_says(client: Any, subject: str, body: str, name: str = "") -> str:
    """One sentence about a single item, for something read late.

    The batch path above is the normal one -- twenty at a time, on the way in.
    This is for an item that arrived while no model would answer: it was kept
    (the gate fails open), it was never summarised, and it has been sitting in
    `pending` ever since waiting for exactly this call.
    """
    if client is None or not (subject or body).strip():
        return ""
    try:
        answer = distil.ask(
            client,
            "memory",
            SYSTEM_PROMPT,
            # The same shape the batch judge sees, so one prompt serves both.
            _who(name) + "[0] " + _summarise(_Item(subject, body)),
            MAX_OUTPUT_TOKENS,
            tools=False,
        )
    except Exception as exc:
        log.info("could not read a held item (%s); it stays held", str(exc)[:120])
        return ""
    return _parse(answer, 1).get(0, "")


def _who(name: str) -> str:
    """The line that puts the person into the request.

    Telling a model it *may* use somebody's name while never telling it the
    name is the sort of instruction that reads fine and does nothing.
    """
    if not name.strip():
        return ""
    return f"The person you are writing for is called {name}.\n\n"


def worth_keeping(client: Any, items: list[Any], name: str = "") -> list[Any]:
    """The items a connector fetched that memory should hold.

    Fails open: returns everything when there is no model or the call fails.
    See the module docstring for why that is the right direction.
    """
    if client is None or not items:
        return items
    kept: list[Any] = []
    for start in range(0, len(items), BATCH):
        batch = items[start : start + BATCH]
        listed = "\n".join(f"[{index}] {_summarise(item)}" for index, item in enumerate(batch))
        try:
            answer = distil.ask(
                client, "memory", SYSTEM_PROMPT, _who(name) + listed, MAX_OUTPUT_TOKENS,
                tools=False,
            )
        except Exception as exc:
            log.info("gatekeeper unavailable (%s); keeping all %d items", exc, len(batch))
            kept.extend(batch)
            continue
        chosen = _parse(answer, len(batch))
        if not answer.strip():
            # No reply at all is not a decision to discard everything. An
            # empty *list* is; an empty string is a model that did not answer.
            log.info("gatekeeper said nothing; keeping all %d items", len(batch))
            kept.extend(batch)
            continue
        dropped = len(batch) - len(chosen)
        if dropped:
            log.info(
                "memory: %d of %d incoming items were not worth keeping",
                dropped,
                len(batch),
                extra={"marvi_kept": len(chosen)},
            )
        observations.record(
            "gate",
            door="ingest",
            offered=len(batch),
            kept=len(chosen),
            example=_summarise(batch[0]) if batch else "",
        )
        for index in sorted(chosen):
            item = batch[index]
            # Carried on the item so the ingest can put it in front of the
            # mind, and the mind can say it instead of reading out an envelope.
            # `MemoryItem` is frozen, hence the replace rather than a set.
            if chosen[index]:
                item = dataclasses.replace(item, says=chosen[index])
            kept.append(item)
    return kept


#: The same judgement, for one fact a conversation is proposing.
#:
#: `memory_remember` was the last unguarded door into the store: the tool a
#: model reaches for mid-sentence, while holding a conversation, when it is
#: least placed to weigh whether something is worth keeping forever. It is how
#: "the user said hello" was written down five times.
ONE_SYSTEM_PROMPT = prompts.text("gatekeeping-one")


#: The most a correction may change. A gate that can rewrite a sentence
#: wholesale is not a gate, it is a second author: the fix has to be a
#: mis-hearing repaired, not a fact restated.
FIX_DRIFT = 0.4


def worth_remembering(client: Any, subject: str, body: str) -> tuple[bool, str]:
    """Whether one proposed fact belongs in memory, and how it should read.

    Returns `(keep, body)`. The body is the corrected sentence when the model
    caught a mis-hearing, and the one it was given otherwise.

    The correction is the half that was missing, and the owner found it before
    the tests did. Told out loud "I have a PS5 controller", the recogniser
    heard "BS5", and this gate -- which is an LLM, and was asked only whether
    the fact was worth keeping -- said KEEP. So the store holds "The user plays
    EA Sports FC 26 on PC using a BS5 controller", and it will say that back
    for as long as it is there.

    Nothing in the pipeline was looking. The recogniser cannot know the word;
    the vocabulary correction only knows names already in memory, and this was
    the turn that would have put it there; and a gate asked KEEP or DROP has no
    way to say "keep it, but that is not a real product".

    Fails open in both directions: an unreachable gate keeps the fact as
    written, and a correction that drifts too far from what was said is
    discarded rather than trusted.
    """
    if client is None or not body.strip():
        return True, body
    try:
        said = distil.ask(
            client,
            "memory",
            ONE_SYSTEM_PROMPT,
            f"Subject: {subject}\nFact: {body}"[: PREVIEW * 2],
            64,
            tools=False,
        )
    except Exception as exc:
        log.info("gatekeeper unavailable (%s); keeping the proposed memory", exc)
        return True, body
    verdict = (said or "").strip()
    keep = not verdict.upper().startswith("DROP") if verdict else True
    fixed = body
    if keep and verdict.upper().startswith("FIX:"):
        candidate = verdict[4:].strip().strip('"')
        # A correction is a word or two, not a rewrite. Measured against the
        # length of what was said rather than an edit distance, because the
        # failure to guard against is the model helpfully restating the fact.
        if candidate and abs(len(candidate) - len(body)) <= max(12, len(body) * FIX_DRIFT):
            fixed = candidate
            log.info("memory: corrected a mis-hearing before storing it")
    observations.record(
        "gate", door="tool", kept=keep, subject=subject, body=body, fixed=fixed
    )
    return keep, fixed
