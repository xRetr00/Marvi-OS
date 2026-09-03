"""Reading across memories rather than counting repeats of one.

`MemoryStore.reflect()` groups episodes by subject and promotes the ones seen
often enough. That is a real operation and it is not this one. It can only ever
notice that something *recurred*; it cannot notice that two things that each
happened once say a third thing together.

Honcho's Dreamer is the shape worth taking. It runs off the critical path over
what has accumulated and draws **inductive conclusions** -- statements nobody
made that follow from several that were -- then withdraws the ones that stop
being supported. Three things it does that this now does too:

* **Conclusions carry their premises.** A derived belief that cannot be traced
  back is one Marvi can only insist on. Stored in `premises`, so "why do you
  think that?" has an answer and a wrong conclusion can be argued with.
* **They are marked as inference.** Written untrusted and sourced `dreaming`,
  because Marvi working something out and the user saying it are not the same
  kind of fact and must not be recalled as though they were.
* **Only its own conclusions are ever withdrawn.** The curator touches nothing
  a person authored, and never
  deletes what it did not write.

## The graph is the point

Marvi has had `entities` and `relations` since the beginning, a Cortex graph view
to render them, and `memory_link` as a tool. The graph on this machine held
**zero entities and zero relations**, because filling it was left to a model
choosing to call a tool mid-conversation, and no model ever did while it had
an answer to give instead.

Dreaming is where that work belongs. It is not on the critical path, it is
already reading the whole recent store, and relating things is the same
operation as concluding from them. Relations it writes are untrusted for the
same reason its memories are.

## Not on the turn

Deliberately scheduled rather than triggered per exchange. `remembering.py`
already runs after a turn and has to be quick, because a queue that falls
behind is a queue that loses memories. This is the slow pass: it reads eighty
memories, thinks about them, and nothing waits on it.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import distil
from .logs import get_logger

log = get_logger("memory")

MAX_OUTPUT_TOKENS = 2_000

#: How many new memories one dream reads. Enough that a conclusion can span
#: several days of a quiet machine, small enough to stay one cheap call.
WINDOW = 80

#: A conclusion drawn from one memory is that memory restated. The whole reason
#: this exists is the sentence neither of two memories contains alone.
MIN_PREMISES = 2

#: Entity names come from a model and end up as graph node labels. A sentence
#: in the subject position makes an unreadable graph and a useless one.
MAX_ENTITY = 60

SYSTEM_PROMPT = (
    "You are the part of an assistant's mind that works things out while it is "
    "idle. You are shown memories it has stored. Find what follows from them "
    "that nobody said.\n"
    "\n"
    "Reply with one JSON object and nothing else:\n"
    '{"conclusions":[{"subject":"<a few words>","body":"<one sentence>",'
    '"from":[<memory ids>]}],\n'
    ' "links":[{"subject":"<name>","predicate":"<verb phrase>","object":"<name>"}],\n'
    ' "retire":[<ids of conclusions that no longer hold>]}\n'
    "\n"
    "Any of the three may be empty, and usually at least one is.\n"
    "\n"
    "conclusions -- things that are true given several of these memories but "
    "are stated in none of them. Each must name at least two memory ids in "
    '"from". A conclusion drawn from one memory is that memory reworded, which '
    "is worth nothing. Do not restate, summarise, or combine memories that "
    "simply agree. Prefer few and specific over many and vague.\n"
    "\n"
    "links -- the people, places, projects and things these memories are "
    "about, and how they relate. Subject and object are short names, not "
    "sentences. The predicate is a verb phrase: 'works on', 'lives in', "
    "'prefers', 'is the developer of'. This is how the assistant's graph of "
    "who and what gets built, so name the same thing the same way every time.\n"
    "\n"
    "retire -- ids from the CONCLUSIONS list below that later memories "
    "contradict or make irrelevant. Only ids from that list. Never retire "
    "something because it is old.\n"
    "\n"
    "Say nothing you are guessing at. An empty answer is a good answer, and a "
    "confident invention is worse than silence -- the assistant will repeat it "
    "back to the person it is about."
)


def _parse(text: str) -> dict[str, Any]:
    """One dream from a model's reply, or nothing.

    Never raises. This runs on a scheduler thread whose other jobs are Marvi's
    background mind, and one that dies takes them with it.
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
    return parsed if isinstance(parsed, dict) else {}


def _shown(memories: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"[{row['id']}] {row['subject']}: {str(row['body'])[:300]}" for row in memories
    )


def _ids(value: Any, known: set[int]) -> list[int]:
    """The memory ids in a model's answer that actually exist.

    A model naming an id it was not shown is a model that invented a premise,
    and a conclusion resting on an invented premise is exactly the thing
    premises were added to prevent.
    """
    if not isinstance(value, list):
        return []
    found: list[int] = []
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number in known and number not in found:
            found.append(number)
    return found


def _name(value: Any) -> str:
    """An entity name, or empty.

    Collapsed and trimmed rather than rejected on length: a model that answers
    with a clause where a name belongs has still identified the right thing,
    and the graph would rather hold a long label than no edge.
    """
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:MAX_ENTITY]


def dream(client: Any, memories: list[dict[str, Any]], conclusions: list[dict[str, Any]]) -> dict:
    """What follows from these memories that none of them says.

    `conclusions` is what has already been concluded, so the model can withdraw
    its own earlier work rather than only adding to it. Returns `{}` for
    "nothing", which is a normal and frequent answer. Never raises.
    """
    if client is None or len(memories) < MIN_PREMISES:
        return {}
    known = {int(row["id"]) for row in memories}
    standing = {int(row["id"]) for row in conclusions}
    try:
        # Through `distil.ask` for the reason its docstring gives: it is the
        # one place that knows a client may be the harness rather than the
        # provider underneath it. `tools=False` because this answers in JSON.
        reply = distil.ask(
            client,
            "memory",
            SYSTEM_PROMPT,
            f"MEMORIES:\n{_shown(memories)}\n\n"
            f"CONCLUSIONS you drew before:\n{_shown(conclusions) or '(none yet)'}",
            MAX_OUTPUT_TOKENS,
            tools=False,
            temperature=0.3,
        )
    except Exception as exc:
        log.info("dreaming unavailable (%s); nothing concluded", exc)
        return {}

    answer = _parse(reply)
    drawn: list[dict[str, Any]] = []
    for item in answer.get("conclusions") or []:
        if not isinstance(item, dict):
            continue
        subject = str(item.get("subject") or "").strip()[:200]
        body = str(item.get("body") or "").strip()
        premises = _ids(item.get("from"), known)
        if not subject or not body or len(premises) < MIN_PREMISES:
            continue
        drawn.append({"subject": subject, "body": body[:2_000], "premises": premises})

    links: list[dict[str, str]] = []
    for item in answer.get("links") or []:
        if not isinstance(item, dict):
            continue
        subject = _name(item.get("subject"))
        predicate = _name(item.get("predicate"))
        obj = _name(item.get("object"))
        # A self-edge is a model filling in a field, not a relation.
        if not (subject and predicate and obj) or subject.lower() == obj.lower():
            continue
        links.append({"subject": subject, "predicate": predicate, "object": obj})

    # Only its own, and only ones it was actually shown. A model asked to
    # withdraw a belief will sometimes withdraw a memory instead.
    retire = _ids(answer.get("retire"), standing)
    # One shape for "nothing", whether the model said nothing or said something
    # unusable. Three empty lists is a truthy dict, and every caller writing
    # `if found` would have been running a write pass over it.
    if not (drawn or links or retire):
        return {}
    return {"conclusions": drawn, "links": links, "retire": retire}


def apply(memory: Any, found: dict[str, Any]) -> dict[str, int]:
    """Write a dream into the store. Returns what changed."""
    concluded = 0
    for item in found.get("conclusions") or []:
        try:
            memory.conclude(item["subject"], item["body"], item["premises"])
            concluded += 1
        except Exception as exc:
            log.warning("could not store a conclusion: %s", exc)

    linked = 0
    for item in found.get("links") or []:
        try:
            memory.link(
                item["subject"],
                item["predicate"],
                item["object"],
                source=memory.DREAMT,
                # Derived, not stated. The graph already renders the two
                # differently; nothing had ever set it to false before.
                trusted=False,
            )
            linked += 1
        except Exception as exc:
            log.warning("could not store a relation: %s", exc)

    retired = sum(1 for memory_id in found.get("retire") or [] if memory.retire(memory_id))
    return {"concluded": concluded, "linked": linked, "retired": retired}
