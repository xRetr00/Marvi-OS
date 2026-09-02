"""What the last conversation was about, for the next one.

Memory holds facts. It is told, in as many words, never to store "the
assistant's own words, pleasantries, or the fact that a conversation
happened" -- and that rule is right, because a store full of "the user said
hello" is the store we already had once.

But it leaves a hole shaped exactly like a hung-up call. End a session, start
another, and Marvi knows the user is a dough chef in Duzce and has no idea they
spent the last twenty minutes on the graph UI. Every session is a cold start.
Typed chat keeps threads; the spoken surface keeps nothing, because a LiveKit
session begins with an empty chat context and nothing has ever written to it.

So: one short note per session about what it was *about*, written when the
session ends, read into the prompt when the next one begins.

## Why this is not memory, and must not become it

A fact is true until it changes. This is true for an afternoon. Keeping them
apart is what stops "we were talking about the graph" turning into a permanent
belief that the user is interested in graphs -- the exact failure mode that
filled the store with marketing email.

So it lives in its own file, holds a handful of entries, and every one of them
expires. `STALE_HOURS` is the whole safety argument: a note about a
conversation three days ago is not continuity, it is a non-sequitur, and being
reminded of it is worse than a cold start.

## Why it is a summary and not a transcript

The alternative -- replaying the last session's messages into the new context --
costs the whole transcript in tokens on every turn of the new session, and
carries every mishearing with it. One sentence costs about twenty.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from . import distil
from .logs import get_logger

log = get_logger("memory")

SETTING = "MARVI_SESSION_CONTINUITY"

#: How long a note stays worth mentioning.
#:
#: Long enough to survive a dropped call, a restart, or a lunch break; short
#: enough that it never becomes "you mentioned three days ago". Continuity is
#: about the conversation that was interrupted, not about history.
STALE_HOURS = 8.0

#: How many notes are kept at all. The prompt only ever shows the newest, so
#: the rest are for a person reading the file.
KEEP = 20

MAX_OUTPUT_TOKENS = 120

#: A note longer than this stops being a reminder and starts being a summary
#: nobody asked for, paid on every turn of the next session.
MAX_CHARS = 220

SYSTEM_PROMPT = (
    "Summarise what this conversation was about in one short sentence, for the "
    "assistant to read at the start of the next one.\n"
    "\n"
    "Write what they were doing or discussing, not what was said. Name the "
    "subject plainly: 'the graph UI in Marvi', 'their exam timetable', "
    "'whether to switch editors'.\n"
    "\n"
    "If it was small talk, a greeting, or nothing in particular, reply exactly: "
    "NOTHING\n"
    "\n"
    "Never include anything the assistant should not repeat aloud."
)


def enabled() -> bool:
    return os.environ.get(SETTING, "on").strip().lower() not in ("0", "false", "no", "off")


def path() -> Path:
    from .paths import root

    return root() / "state" / "continuity.json"


def _load() -> list[dict[str, Any]]:
    try:
        found = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return found if isinstance(found, list) else []


#: Answers that are the model agreeing there was nothing, in other words.
#:
#: It is told to reply exactly NOTHING for small talk and mostly does, but the
#: file has "Greeting" in it -- one word, no subject, and it would have been
#: read into the next session as though it were a topic. A note has to name
#: something to be worth carrying; these name the absence of one.
NOTHING_MUCH = (
    "nothing",
    "greeting",
    "greetings",
    "small talk",
    "smalltalk",
    "chitchat",
    "chit-chat",
    "casual conversation",
    "a greeting",
    "general conversation",
    "no particular subject",
    "no specific topic",
)


def worth_keeping(text: str) -> bool:
    """Whether a summary names a subject, rather than the lack of one."""
    clean = " ".join(str(text or "").split()).strip().strip(".").lower()
    if not clean:
        return False
    if clean.startswith("nothing"):
        return False
    return clean not in NOTHING_MUCH


def remember(text: str) -> None:
    """Keep one note about a session that just ended. Never raises."""
    clean = " ".join(str(text or "").split())[:MAX_CHARS]
    if not worth_keeping(clean):
        log.info("nothing worth carrying from this session (%r)", clean[:60])
        return
    notes = [*_load(), {"at": round(time.time(), 3), "about": clean}][-KEEP:]
    try:
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(notes, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:  # pragma: no cover - depends on the filesystem
        log.info("could not keep a note about this session: %s", exc)


def recent() -> str:
    """What the last conversation was about, or "" when there is nothing to say."""
    if not enabled():
        return ""
    notes = _load()
    if not notes:
        return ""
    last = notes[-1]
    age = time.time() - float(last.get("at") or 0)
    if age > STALE_HOURS * 3600:
        return ""
    return str(last.get("about") or "")


def block() -> str:
    """The prompt line for a session that is starting, or "".

    Deliberately hedged. The user may have hung up mid-sentence or may have
    moved on entirely, and an assistant that opens by insisting on the previous
    topic is worse than one that forgot -- so this says what it was and leaves
    the decision to her.
    """
    about = recent()
    if not about:
        return ""
    return (
        "# Where you left off\n\n"
        f"Your last conversation was about {about}\n\n"
        "Mention it only if it fits what they say now. They may have moved on, "
        "and they did not ask you to pick up where you stopped."
    )


def summarise(client: Any, exchanges: list[tuple[str, str]]) -> str:
    """One sentence about a finished session. "" when there is nothing to keep."""
    if client is None or not exchanges:
        return ""
    listed = "\n".join(
        f"User: {said}\nAssistant: {reply}" for said, reply in exchanges[-12:]
    )[:4_000]
    try:
        answer = distil.ask(
            client, "memory", SYSTEM_PROMPT, listed, MAX_OUTPUT_TOKENS, tools=False
        )
    except Exception as exc:
        log.info("could not summarise the session (%s); the next one starts cold", exc)
        return ""
    clean = " ".join((answer or "").split())
    return "" if clean.upper().startswith("NOTHING") else clean[:MAX_CHARS]
