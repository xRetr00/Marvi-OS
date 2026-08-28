"""Turning a finished task into a skill, on the same pass as memory.

After a turn, fork off and ask *"should any skill be written or
patched?"* -- and treat the answer as being about **how to do this class of
task**, separately from what memory holds.

Their distinction is the one worth copying verbatim:

> Memory says "who the user is and what the current situation and state of your
> operations are"; skills say "how to do this class of task for this user".

And the signal they name first is the one nobody thinks to use:

> Frustration is a FIRST-CLASS skill signal. "stop doing X", "don't format like
> this", "I hate when you Y" -- embed the lesson in the skill that governs that
> task so the next session starts fixed.

That is exactly the failure Marvi has. Corrections about *how* she works have
nowhere to go: memory holds facts about the world, the prompt is fixed, and the
same mistake returns next session. This gives it somewhere.

## Patch before create

Their preference order, kept because it is what stops a skills directory
filling with one-off notes named after today's task:

1. patch a skill that already covers this;
2. otherwise write a new one, named for the *class* of task rather than the
   instance -- `handling-the-smart-room`, never `fix-the-light-again`.

## Proposed, not written

Nothing here writes to disk on its own.
A skill is instructions Marvi will follow later, so a model that can silently
write them is a model that can silently rewrite its own behaviour -- and the
Skills page already has a review flow, because that argument was settled when
skills could be installed from a store. This produces a proposal; a person
accepts it.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import distil
from .logs import get_logger

log = get_logger("memory")

MAX_OUTPUT_TOKENS = 1_200
#: A skill body longer than this is a document, not instructions. The store's
#: own guidance is that a skill advertises in ~100 tokens and loads in under
#: 5,000; this keeps a proposal inside that.
MAX_BODY_CHARS = 6_000

#: A name has to be a directory name, and it has to be about a class of task.
VALID_NAME = re.compile(r"^[a-z][a-z0-9-]{2,48}$")

SYSTEM_PROMPT = (
    "You decide whether an assistant should write down how to do something, "
    "after watching it do that thing once.\n"
    "Reply with one JSON object and nothing else:\n"
    '  {"act":"none"}\n'
    '  {"act":"patch","name":"existing-skill-name","body":"<the full new SKILL.md body>",'
    '"why":"<one sentence>"}\n'
    '  {"act":"create","name":"class-of-task","description":"<one line>",'
    '"body":"<the SKILL.md body>","why":"<one sentence>"}\n'
    "\n"
    '"none" is the right answer almost always. Reply {"act":"none"} unless one '
    "of these happened:\n"
    "- The user corrected how you work -- your style, format, verbosity, or "
    "approach. Frustration is the strongest signal there is: 'stop doing that', "
    "'not like this', 'I told you already'. The lesson belongs in the skill "
    "that governs the task, so the next session starts fixed.\n"
    "- A non-obvious technique, fix, or sequence of steps worked, and would "
    "have to be worked out again next time.\n"
    "- A skill that was used turned out wrong, missing a step, or out of date.\n"
    "\n"
    "Rules:\n"
    "- Patch before you create. If a listed skill covers this class of task, "
    "patch it and return its whole new body.\n"
    "- Name a class of task, never an instance. 'controlling-the-room', not "
    "'fix-the-light-again' or 'the-thing-from-tuesday'. If the name only makes "
    "sense for today, patch something instead or answer none.\n"
    "- Write instructions for doing the task, not a story about what happened. "
    "No dates, no 'the user asked me to'.\n"
    "- Facts about the user are memory, not a skill. Skills are how to do "
    "things."
)


def _skills_listing(available: list[Any]) -> str:
    return (
        "\n".join(f"- {skill.name}: {skill.description}" for skill in available)
        or "(no skills installed)"
    )


def _parse(text: str) -> dict[str, Any]:
    """One proposal from a model's reply, or nothing.

    Never raises: this runs on the memory worker's thread, behind a queue, and
    a thread that dies takes every later turn's memory with it.
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


def propose(client: Any, user: str, assistant: str, available: list[Any]) -> dict[str, Any]:
    """Whether this turn taught something worth writing down.

    Returns `{}` for "nothing", which is the usual answer and must stay cheap
    to reach. Never raises.
    """
    if client is None or not (user.strip() and assistant.strip()):
        return {}
    try:
        # Through `distil.ask` for the reason its docstring gives: it is the
        # one place that knows a client may be the harness rather than the
        # provider underneath it. `tools=False` because this answers in JSON.
        answer = distil.ask(
            client,
            "memory",
            SYSTEM_PROMPT,
            f"Skills that exist:\n{_skills_listing(available)}\n\n"
            f"The exchange:\nUser: {user.strip()[:4000]}\n\n"
            f"Assistant: {assistant.strip()[:4000]}",
            MAX_OUTPUT_TOKENS,
            tools=False,
        )
    except Exception as exc:
        log.info("skill review unavailable (%s); nothing proposed", exc)
        return {}

    proposal = _parse(answer)
    act = str(proposal.get("act") or "none").strip().lower()
    if act not in ("patch", "create"):
        return {}

    name = str(proposal.get("name") or "").strip().lower()
    body = str(proposal.get("body") or "").strip()
    if not VALID_NAME.match(name) or not body:
        log.info("skill proposal discarded: %r is not a usable skill name", name)
        return {}
    known = {skill.name for skill in available}
    if act == "patch" and name not in known:
        # A patch to something that does not exist is a create that named
        # itself wrongly, and the naming rules matter more for a create.
        act = "create"
    if act == "create" and name in known:
        act = "patch"

    return {
        "act": act,
        "name": name,
        "description": str(proposal.get("description") or "").strip()[:200],
        "body": body[:MAX_BODY_CHARS],
        "why": str(proposal.get("why") or "").strip()[:300],
    }
