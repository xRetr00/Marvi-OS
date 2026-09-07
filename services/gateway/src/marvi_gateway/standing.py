"""Who Marvi is talking to, known before anyone says anything.

Marvi starts every session empty. Recall fills the gap a turn at a time, and
only for turns that ask something a search can match -- so until somebody says
a keyword, she is dealing with a stranger. Asked "how are we doing?" she has a
name from `USER.md` and nothing else: not what they are building, not what they
use, not what they asked her to stop doing. The person is in the store the
whole time and she cannot see them, because seeing them requires a question
that happens to retrieve them.

`continuity` fixed the neighbouring hole -- what the last conversation was
about -- and stops there by design, because a note about an afternoon must
never become a permanent belief. This is the other half: what is true about
this person across all of it.

## Why it is one standing block and not more recall

Recall is per-turn, keyed to what was just said, and it is the wrong shape for
"who am I speaking to". A summary of the whole store answers that once, costs
its tokens once, and is right on the turns that ask nothing -- which is most of
them, and exactly the turns where a cold answer sounds like a stranger.

## Why it is not rebuilt per turn

It changes on the timescale that a person changes. Rebuilding it per turn would
put a model call in front of every reply for a paragraph that is the same
paragraph. So it is written to disk, read from there, and rebuilt in the
background when it goes stale or when the store has moved underneath it.

## What keeps it from becoming a second memory

`MAX_CHARS`. A profile that grows without limit is the store again, in the
prompt, on every turn. Six or seven lines is a person; thirty is a dossier
nobody reads, least of all a model with a spoken turn to answer.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from . import distil
from .logs import get_logger

log = get_logger("memory")

SETTING = "MARVI_STANDING_SUMMARY"

#: How long before it is rebuilt. A person does not change hourly, and the
#: rebuild is a model call over the whole store.
STALE_HOURS = 12.0

#: Or sooner, if this many memories have arrived or gone since it was written.
#: A summary that predates a week of new facts is a summary of somebody else.
MOVED_BY = 8

#: The whole point is that this is affordable on every turn.
MAX_CHARS = 900

#: How many memories the summary is built from. Enough to be a portrait,
#: bounded so one call cannot cost a minute.
READS = 120

# The first version of this asked for a portrait and got one, which was the
# mistake. It wrote "prioritizing painful workflows over local compliance" and
# "uses Brave for search to save credits" -- both traceable to something in the
# store, both an interpretation of it, and both the kind of line that is true
# this month and misleading next. A brief that goes in front of every single
# turn cannot afford either: a stale detail is repeated with confidence for as
# long as it sits there, and an inferred motive is repeated as though the
# person had said it.
#
# So it is deliberately boring. This is infrastructure, not prose about
# somebody. The three rules below are the whole design.
SYSTEM_PROMPT = (
    "Here is everything an assistant remembers about the person it works for. "
    "Write the short standing brief it carries into every conversation, so it "
    "never opens one as a stranger.\n"
    "\n"
    "Include only what is stable and certain: who they are, the major things "
    "they are building, durable preferences, the environment they work in "
    "day to day.\n"
    "\n"
    "Leave out anything temporary or inferred. No current tool of the month, "
    "no app they mentioned once, no habit from a single day, and no motive or "
    "reason you worked out rather than were told. If you are not sure it will "
    "still be true in six months, leave it out.\n"
    "\n"
    "Every sentence must come from the notes below and say no more than they "
    "do. If a sentence needs you to interpret or join things up to write it, "
    "do not write it. Plain and dull is correct here.\n"
    "\n"
    "Four or five sentences. Third person -- 'he is building', not 'you are "
    "building'. Do not address the assistant, do not give it instructions, do "
    "not mention memory or where any of this came from. No preamble, no "
    "heading, no closing line. Just the brief."
)

#: Appended when the user's name is known, which it nearly always is.
#:
#: It was not being told, and it invented one. The brief that went into every
#: turn for half a day opened:
#:
#:     Brady Vine is building Marvi, a voice-first local AI assistant, under
#:     the codename Marvey.
#:
#: There is no Brady Vine. The notes say Shereef, in a memory whose whole body
#: is "The user's name is Shereef", and the model wrote a name anyway --
#: asserted as fact, in front of every sentence she spoke.
NAME_RULE = (
    chr(10) * 2 + "The person is called {name}. Use that name and no other. Never "
    "introduce a name that is not in the notes below."
)

#: A brief is what is true in six months. These say otherwise.
#:
#: The prompt asks for exactly this and was ignored -- the live brief carried
#: "The Agent voice engine keeps restarting and the Sidecar process is
#: currently down", four hours after both were fixed, and Marvi recited it
#: back as current when asked what was wrong with her. Asking is not enough
#: when the cost of a slip is a standing falsehood.
TRANSIENT = re.compile(
    r"\b(currently|right now|at the moment|keeps? (?:restarting|failing|crashing)|"
    r"is (?:down|offline|broken|failing)|are (?:down|offline)|"
    r"needs? (?:re-?authentication|re-?authorization)|cannot check|is on at|"
    r"at \d+ percent)\b",
    re.I,
)


def _sentences(text: str) -> list[str]:
    """Split on sentence ends, keeping the punctuation."""
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def settled(text: str, name: str = "") -> str:
    """The part of a brief worth carrying into every turn.

    Three things went wrong at once in the live brief and each needed its own
    answer: a name nobody has, a paragraph of this morning's system state, and
    a hard cut at `MAX_CHARS` that left the last sentence as "Shereef is lik".

    Returns "" when the brief is about somebody else -- there is no repairing
    that one, and the previous brief, stale but about the right person, is
    better than a current one about a stranger.
    """
    kept = []
    for sentence in _sentences(text):
        if TRANSIENT.search(sentence):
            log.info("standing brief: dropped a sentence about right now")
            continue
        kept.append(sentence)
    if name:
        # Only the opening sentence, which is the one that says whose brief
        # this is. A later mention of a friend or a colleague is legitimate.
        opening = kept[0] if kept else ""
        others = [
            found
            for found in re.findall(r"\b[A-Z][a-z]+(?: [A-Z][a-z]+)+\b", opening)
            if name.lower() not in found.lower()
        ]
        if others:
            log.warning(
                "standing brief names %s and not %s; keeping the previous one",
                others[0], name,
            )
            return ""
    # Whole sentences only, up to the cap.
    out = ""
    for sentence in kept:
        if len(out) + len(sentence) + 1 > MAX_CHARS:
            break
        out = f"{out} {sentence}".strip()
    return out


def enabled() -> bool:
    return os.environ.get(SETTING, "on").strip().lower() not in ("0", "false", "no", "off")


def path() -> Path:
    from .paths import root

    return root() / "state" / "standing.json"


def _read() -> dict[str, Any]:
    try:
        return json.loads(path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(text: str, held: int) -> None:
    try:
        path().parent.mkdir(parents=True, exist_ok=True)
        path().write_text(
            json.dumps({"text": text, "at": time.time(), "held": held}, indent=1),
            encoding="utf-8",
        )
    except Exception as exc:  # pragma: no cover - depends on the disk
        log.warning("could not save the standing brief: %s", exc)


def stale(saved: dict[str, Any], held: int) -> bool:
    """Whether the saved brief still describes the store it was built from."""
    if not saved.get("text"):
        return True
    if time.time() - float(saved.get("at") or 0) > STALE_HOURS * 3600:
        return True
    return abs(held - int(saved.get("held") or 0)) >= MOVED_BY


def compose(store: Any, client: Any) -> str:
    """Build the brief from the store. Returns "" if it cannot."""
    try:
        rows = store.recent(limit=READS)
    except Exception as exc:  # pragma: no cover - depends on the store
        log.warning("standing brief: cannot read the store: %s", exc)
        return ""
    lines = []
    for row in rows:
        body = str(row.get("body") or "").strip()
        # An outside voice must not get to write the brief that goes in front
        # of every turn. This is the same boundary `recall_block` keeps, for
        # the same reason and with more at stake: recall is one turn, this is
        # all of them.
        if not body or row.get("external"):
            continue
        subject = str(row.get("subject") or "").strip()
        lines.append(f"- {subject}: {body}" if subject else f"- {body}")
    if not lines:
        return ""
    try:
        name = known_name()
        said = distil.ask(
            client,
            "memory",
            SYSTEM_PROMPT + (NAME_RULE.format(name=name) if name else ""),
            chr(10).join(lines)[:6000],
            400,
            tools=False,
        )
    except Exception as exc:
        log.info("standing brief unavailable (%s)", exc)
        return ""
    if not said or not said.strip():
        return ""
    # Checked, not trusted. The prompt asks for all of this and the model
    # wrote "Brady Vine is building Marvi" anyway, together with a
    # paragraph of that morning's system state -- and both stood in front
    # of every sentence Marvi spoke for half a day. See `settled`.
    return settled(said.strip(), name)


def known_name() -> str:
    """The user's name, from the file that holds it. Empty when unknown."""
    import contextlib

    with contextlib.suppress(Exception):
        from . import voicing
        from .identity import IdentityFiles

        return str(
            voicing.name_of(IdentityFiles().user_path.read_text(encoding="utf-8")) or ""
        )
    return ""


def refresh(store: Any, client: Any) -> str:
    """Rebuild if it has gone stale, and return whatever is current."""
    if not enabled():
        return ""
    saved = _read()
    try:
        held = int(store.count())
    except Exception:
        held = 0
    if not stale(saved, held):
        return str(saved.get("text") or "")
    if client is None:
        # Nothing to build with. The old brief is better than none: it is out
        # of date about a person, not wrong about them.
        return str(saved.get("text") or "")
    text = compose(store, client)
    if text:
        _write(text, held)
        log.info("standing brief rebuilt from %d memories", held)
        return text
    return str(saved.get("text") or "")


def ensure(store: Any, client: Any) -> None:
    """Rebuild in the background, so no turn ever waits for it."""
    if not enabled():
        return
    threading.Thread(
        target=lambda: refresh(store, client), daemon=True, name="marvi-standing"
    ).start()


def block() -> str:
    """The brief, as prompt text. Read from disk, so this is free."""
    if not enabled():
        return ""
    text = str(_read().get("text") or "").strip()
    if not text:
        return ""
    # Named, and named as standing rather than as recall. Without a heading the
    # Agent appends a paragraph of prose about a person and it reads as a note
    # somebody left rather than as what she knows.
    #
    # "answer as yourself" is here because it is the failure this whole block
    # risks re-introducing: a paragraph written *about* the user, in the third
    # person, sitting in the prompt is exactly the shape that produced "she
    # works fully locally, she uses..." out loud. It is said once, about the
    # block, rather than glued to any sentence in it.
    return (
        "# Who you are talking to\n\n"
        "This is true on every turn. You know it already -- do not look it up, "
        "do not read it back, and do not mention having notes. Talk to them "
        "like someone you know.\n\n" + text
    )
