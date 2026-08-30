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

SYSTEM_PROMPT = (
    "Here is everything an assistant remembers about the person it works for. "
    "Write the short standing brief it should carry into every conversation -- "
    "who this person is and what matters about them, so it never has to open a "
    "conversation as a stranger.\n"
    "\n"
    "Six lines at most, each one plain and specific. Cover what they are "
    "working on, what they use, how they like to be dealt with, and the people "
    "and places that come up. Leave out anything you would not want said back "
    "to them.\n"
    "\n"
    "Write about them in the third person -- 'he is building', not 'you are "
    "building'. Do not address the assistant, do not give it instructions, do "
    "not mention memory or where any of this came from. No preamble, no "
    "heading, no closing line. Just the brief."
)


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
        said = distil.ask(
            client, "memory", SYSTEM_PROMPT, "\n".join(lines)[:6000], 400, tools=False
        )
    except Exception as exc:
        log.info("standing brief unavailable (%s)", exc)
        return ""
    text = " ".join((said or "").split("\n\n")[0].split()) if said else ""
    return said.strip()[:MAX_CHARS] if said and text else ""


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
