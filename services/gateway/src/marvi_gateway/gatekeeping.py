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

import json
import re
from typing import Any

from . import distil, observations
from .logs import get_logger

log = get_logger("memory")

#: How many items one call judges. Large enough that a poll is usually one
#: call, small enough that the prompt stays readable to the model.
BATCH = 20

MAX_OUTPUT_TOKENS = 400

#: How much of each item the judge sees. A marketing email announces itself in
#: the first line; so does a letter from a person.
PREVIEW = 400

SYSTEM_PROMPT = (
    "You are the gatekeeper for an assistant's long-term memory. Items below "
    "arrived from a connected account -- email, calendar, issues -- and you "
    "decide which are worth remembering about the person.\n"
    "\n"
    'Reply with one JSON object and nothing else: {"keep":[0,3,7]}\n'
    "The numbers are the indexes of items worth keeping. An empty list is "
    "usually right.\n"
    "\n"
    "Keep an item when it says something about this person's life, work, "
    "plans, relationships or commitments:\n"
    "  a message from a real person written to them\n"
    "  an appointment, a booking, a deadline, a delivery they are expecting\n"
    "  a bill, a result, a decision that affects them\n"
    "\n"
    "Do not keep an item that was broadcast to a list, or that says nothing "
    "about them:\n"
    "  newsletters, product announcements, marketing, sales, discount offers\n"
    "  automated notifications: 'you appeared in searches', 'your weekly "
    "summary', social media activity\n"
    "  security alerts and receipts for actions they already know they took\n"
    "\n"
    "The test is whether the assistant would look foolish not knowing this "
    "next week. A newsletter fails it however interesting the subject sounds."
)


def _parse(text: str, total: int) -> set[int]:
    """Indexes to keep, from a model's reply. Never raises."""
    body = (text or "").strip().strip("`")
    if body.lower().startswith("json"):
        body = body[4:].strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        return set()
    try:
        parsed = json.loads(body[start : end + 1])
    except ValueError:
        return set()
    kept = parsed.get("keep") if isinstance(parsed, dict) else None
    if not isinstance(kept, list):
        return set()
    return {int(n) for n in kept if isinstance(n, (int, float)) and 0 <= int(n) < total}


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


def worth_keeping(client: Any, items: list[Any]) -> list[Any]:
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
                client, "memory", SYSTEM_PROMPT, listed, MAX_OUTPUT_TOKENS, tools=False
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
        kept.extend(batch[index] for index in sorted(chosen))
    return kept


#: The same judgement, for one fact a conversation is proposing.
#:
#: `memory_remember` was the last unguarded door into the store: the tool a
#: model reaches for mid-sentence, while holding a conversation, when it is
#: least placed to weigh whether something is worth keeping forever. It is how
#: "the user said hello" was written down five times.
ONE_SYSTEM_PROMPT = (
    "An assistant wants to write this into its long-term memory about the "
    "person it works for. Should it?\n"
    "\n"
    "Reply with one word: KEEP or DROP.\n"
    "\n"
    "KEEP a durable fact about them -- a possession, a person in their life, "
    "a plan with a date, a tool they use, a preference they stated, a health "
    "fact, where they live or work.\n"
    "\n"
    "DROP anything about the conversation itself: that they greeted you, "
    "thanked you, asked a question, or that a tool ran. DROP the assistant's "
    "own words and opinions. DROP anything already true on every turn, like "
    "their name.\n"
    "\n"
    "The test is whether the assistant would look foolish not knowing it next "
    "week."
)


def worth_remembering(client: Any, subject: str, body: str) -> bool:
    """Whether one proposed fact belongs in memory. Fails open."""
    if client is None or not body.strip():
        return True
    try:
        said = distil.ask(
            client,
            "memory",
            ONE_SYSTEM_PROMPT,
            f"Subject: {subject}\nFact: {body}"[: PREVIEW * 2],
            8,
            tools=False,
        )
    except Exception as exc:
        log.info("gatekeeper unavailable (%s); keeping the proposed memory", exc)
        return True
    verdict = (said or "").strip().upper()
    keep = not verdict.startswith("DROP") if verdict else True
    observations.record("gate", door="tool", kept=keep, subject=subject, body=body)
    return keep
