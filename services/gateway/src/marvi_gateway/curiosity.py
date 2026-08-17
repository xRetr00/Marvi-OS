"""How Marvi learns who it is working for.

`SOUL.md` is authored and Marvi never writes it. `USER.md` is the opposite:
it starts as a template full of "not known yet" and Marvi fills it in by paying
attention.

Two halves, and they are deliberately different mechanisms:

* **Noticing.** Most of what ends up here is volunteered. "I'm a software
  engineer", "call me Shereef", "I'm usually asleep by one" — all said in
  passing, none of it in answer to a question. Noticing is free and always on.
* **Asking.** Occasionally something matters enough to ask for, and the name is
  the obvious case: without it Marvi cannot address anyone. Asking is rationed
  hard, because the failure mode here is not "Marvi learns slowly", it is
  **Marvi becomes an interrogation** and gets switched off.

## Why the limits are in code, not in the prompt

A model told to "ask occasionally, don't be annoying" will be fine for a while
and then have a chatty afternoon. Annoyance is cumulative and the model cannot
feel it, so the ceiling is enforced here:

* one question per conversation, at most;
* a long cooldown between questions, whatever the model would prefer;
* never the same gap twice, and never again once declined;
* nothing asked at all until there is something worth asking about.

The model still decides *whether this moment suits* and *how to phrase it*,
which is the part it is good at. It does not get to decide how often.

Declining is permanent and silent. Someone who does not want to say what they
do for work should not be asked a second time in a different shape.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .identity import IdentityFiles
from .logs import get_logger

log = get_logger("identity")

# Asking more often than this is how an assistant becomes a form to fill in.
DEFAULT_COOLDOWN_HOURS = 20
# Nothing is asked before this many exchanges: a question in the first breath of
# a conversation reads as an interruption, not as interest.
MIN_TURNS_BEFORE_ASKING = 2


@dataclass(frozen=True)
class Gap:
    """Something Marvi does not know, and why it would help to."""

    key: str
    heading: str
    #: What the model is told to find out. Not a script — it phrases its own.
    prompt: str
    #: Lower goes first. Name is 0 because everything else reads oddly without it.
    priority: int = 5


GAPS: tuple[Gap, ...] = (
    Gap(
        "name",
        "Name",
        "their name, or what they would like to be called",
        priority=0,
    ),
    Gap(
        "address",
        "How to address them",
        "how they want to be addressed — pronouns, or a preferred form of their name",
        priority=1,
    ),
    Gap(
        "work",
        "Work",
        "what they do for work, in enough detail to be useful context",
        priority=2,
    ),
    Gap(
        "rhythm",
        "Hours and rhythm",
        "the shape of their day — when they start, when they wind down",
        priority=3,
    ),
    Gap(
        "preferences",
        "Standing preferences",
        "a standing preference about how Marvi should behave for them",
        priority=4,
    ),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS gaps (
    key       TEXT PRIMARY KEY,
    state     TEXT NOT NULL,          -- open | filled | declined
    value     TEXT NOT NULL DEFAULT '',
    asked_at  TEXT,
    settled_at TEXT
);
"""

# Marvi writes USER.md, so it needs to be obvious which lines are its doing.
UNKNOWN = "Not known yet."


def default_user_template() -> str:
    headings = "\n\n".join(f"## {gap.heading}\n\n{UNKNOWN}" for gap in GAPS)
    return f"# About the person I work for\n\n{headings}\n"


class Curiosity:
    """Tracks what Marvi knows, what it may ask, and when it last asked."""

    def __init__(
        self,
        path: Path | None = None,
        identity: IdentityFiles | None = None,
        cooldown_hours: int = DEFAULT_COOLDOWN_HOURS,
    ) -> None:
        self.identity = identity or IdentityFiles()
        self.cooldown = timedelta(hours=cooldown_hours)
        self.path = path or (self.identity.dir / "curiosity.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        for gap in GAPS:
            self._db.execute(
                "INSERT OR IGNORE INTO gaps (key, state) VALUES (?, 'open')", (gap.key,)
            )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # -- state ---------------------------------------------------------------

    def _row(self, key: str) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM gaps WHERE key = ?", (key,)).fetchone()

    def state(self) -> dict[str, dict[str, Any]]:
        return {
            row["key"]: {
                "state": row["state"],
                "value": row["value"],
                "asked_at": row["asked_at"],
            }
            for row in self._db.execute("SELECT * FROM gaps")
        }

    def open_gaps(self) -> list[Gap]:
        rows = {r["key"]: r["state"] for r in self._db.execute("SELECT * FROM gaps")}
        return sorted(
            (gap for gap in GAPS if rows.get(gap.key, "open") == "open"),
            key=lambda gap: gap.priority,
        )

    def last_asked(self) -> datetime | None:
        row = self._db.execute(
            "SELECT MAX(asked_at) AS latest FROM gaps WHERE asked_at IS NOT NULL"
        ).fetchone()
        if not row or not row["latest"]:
            return None
        try:
            return datetime.fromisoformat(row["latest"])
        except ValueError:
            return None

    # -- asking --------------------------------------------------------------

    def may_ask(self, turns_this_session: int = 99, now: datetime | None = None) -> Gap | None:
        """The one gap Marvi is allowed to raise, or None. Usually None.

        Returning None is the normal answer, and the caller must treat it as
        "say nothing about it" rather than "ask anyway, more subtly".
        """
        if turns_this_session < MIN_TURNS_BEFORE_ASKING:
            return None
        gaps = self.open_gaps()
        if not gaps:
            return None
        previous = self.last_asked()
        if previous is not None:
            moment = now or datetime.now(UTC)
            if moment - previous < self.cooldown:
                return None
        return gaps[0]

    def mark_asked(self, key: str, now: datetime | None = None) -> None:
        self._db.execute(
            "UPDATE gaps SET asked_at = ? WHERE key = ?",
            ((now or datetime.now(UTC)).isoformat(), key),
        )
        self._db.commit()
        log.info("asked about %s", key)

    def decline(self, key: str) -> None:
        """Never ask this again, in any form.

        Someone who does not want to say what they do for work should not be
        asked a second time with different words.
        """
        self._db.execute(
            "UPDATE gaps SET state = 'declined', settled_at = ? WHERE key = ?",
            (datetime.now(UTC).isoformat(), key),
        )
        self._db.commit()
        log.info("declined to answer about %s; not asking again", key)

    # -- learning -------------------------------------------------------------

    def learn(self, key: str, value: str) -> bool:
        """Record something and write it into `USER.md`."""
        cleaned = " ".join((value or "").split())[:300]
        gap = next((g for g in GAPS if g.key == key), None)
        if gap is None or not cleaned:
            return False
        self._db.execute(
            "UPDATE gaps SET state = 'filled', value = ?, settled_at = ? WHERE key = ?",
            (cleaned, datetime.now(UTC).isoformat(), key),
        )
        self._db.commit()
        self._rewrite()
        log.info("learned %s", key, extra={"marvi_value": cleaned})
        return True

    def forget(self, key: str) -> None:
        """Back to unknown, and askable again — the Identity page's undo."""
        self._db.execute(
            "UPDATE gaps SET state = 'open', value = '', asked_at = NULL,"
            " settled_at = NULL WHERE key = ?",
            (key,),
        )
        self._db.commit()
        self._rewrite()

    def _rewrite(self) -> None:
        """Regenerate `USER.md` from what is known.

        Regenerated rather than appended so the file cannot drift into a pile of
        contradicting notes. Anything the user typed by hand under a heading
        Marvi does not own is preserved below.
        """
        known = {row["key"]: row["value"] for row in self._db.execute("SELECT * FROM gaps")}
        sections = []
        for gap in GAPS:
            value = known.get(gap.key) or UNKNOWN
            sections.append(f"## {gap.heading}\n\n{value}")
        body = "# About the person I work for\n\n" + "\n\n".join(sections) + "\n"

        handwritten = self._handwritten()
        if handwritten:
            body += f"\n{handwritten}\n"
        self.identity.write_user(body)

    def _handwritten(self) -> str:
        """Whatever the user added under their own headings, kept verbatim."""
        existing = self.identity.read().user
        if not existing:
            return ""
        owned = {f"## {gap.heading}" for gap in GAPS}
        kept: list[str] = []
        keeping = False
        for line in existing.splitlines():
            if line.startswith("## "):
                keeping = line.strip() not in owned
            elif line.startswith("# "):
                keeping = False
            if keeping:
                kept.append(line)
        return "\n".join(kept).strip()

    # -- the prompt fragment ---------------------------------------------------

    def guidance(self, gap: Gap | None = None) -> str:
        """What to append to the system prompt about learning the user.

        The gap is passed in rather than re-derived, because the caller has
        already spent the rate-limit budget deciding on it. Re-deriving here
        would consult a cooldown that the caller's own decision just started,
        and the invitation would vanish from the very prompt it was meant for.
        """
        lines = [
            "You are still learning who this person is. When they mention "
            "something lasting about themselves — their name, their work, their "
            "hours, how they want to be treated — record it with remember_about_user. "
            "Do not thank them for it or make a moment of it."
        ]
        if gap is not None:
            lines.append(
                f"You do not yet know {gap.prompt}. If this conversation offers a "
                "natural opening, ask once, in your own words, as an aside rather "
                "than a question on a form. If it does not, say nothing about it — "
                "there will be other conversations. Never ask more than this one "
                "thing, and if they deflect, call forget_about_user and let it go."
            )
        return "\n".join(lines)


# -- extraction ----------------------------------------------------------------

# A cheap first pass for the phrasings that are unmistakable. The model handles
# everything else through the tool; this exists so the most common case — a name
# offered plainly — does not depend on a model call going well.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # The lead-in is case-insensitive, the name is not: requiring a capital is
    # most of what stops "I'm tired" from being read as an introduction.
    (
        "name",
        re.compile(
            r"(?i:\b(?:i'?m|i am|my name'?s?|my name is|call me)\s+)([A-Z][\w'-]{1,30})\b"
        ),
    ),
)


def obvious_facts(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for key, pattern in PATTERNS:
        match = pattern.search(text or "")
        if match:
            candidate = match.group(1).strip()
            # "I'm fine", "I'm working" and friends are not names.
            if candidate.lower() in {
                "fine", "good", "okay", "ok", "here", "back", "sorry", "done",
                "working", "trying", "going", "looking", "just", "not", "the",
            }:
                continue
            found[key] = candidate
    return found


def tool_schemas() -> list[dict[str, Any]]:
    """The two tools the model uses to maintain `USER.md`."""
    keys = [gap.key for gap in GAPS]
    return [
        {
            "name": "remember_about_user",
            "description": (
                "Record something lasting about the user in their profile. Only for "
                "things true on every future turn, never for one-off facts — those "
                "are memories. Do not announce that you used this."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "enum": keys},
                    "value": {"type": "string"},
                },
                "required": ["key", "value"],
            },
        },
        {
            "name": "forget_about_user",
            "description": (
                "Stop asking about this. Use it when the user deflects, changes the "
                "subject, or says they would rather not. Marvi will never raise it "
                "again."
            ),
            "parameters": {
                "type": "object",
                "properties": {"key": {"type": "string", "enum": keys}},
                "required": ["key"],
            },
        },
    ]


def handle_tool(curiosity: Curiosity, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute one of the two tools above. Returns a router-shaped result."""
    key = str(arguments.get("key", ""))
    if name == "remember_about_user":
        ok = curiosity.learn(key, str(arguments.get("value", "")))
        return {"status": "executed" if ok else "failed", "result": {"recorded": ok}}
    if name == "forget_about_user":
        curiosity.decline(key)
        return {"status": "executed", "result": {"dropped": key}}
    return {"status": "failed", "error": f"unknown tool {name}"}


def seed_identity(identity: IdentityFiles, repo_root: Path) -> dict[str, bool]:
    """Put the shipped defaults in place on first run.

    Seeded once and **never overwritten**. `SOUL.md` in particular is the user's
    to edit, and an update that silently replaced their version would be the
    worst possible behaviour for a file describing who Marvi is.
    """
    written = {"soul": False, "user": False}
    shipped_soul = repo_root / "config" / "SOUL.md"
    if not identity.soul_path.exists() and shipped_soul.exists():
        identity.write_soul(shipped_soul.read_text(encoding="utf-8"))
        written["soul"] = True
    if not identity.user_path.exists():
        identity.write_user(default_user_template())
        written["user"] = True
    if any(written.values()):
        log.info("seeded identity files", extra={"marvi_written": json.dumps(written)})
    return written
