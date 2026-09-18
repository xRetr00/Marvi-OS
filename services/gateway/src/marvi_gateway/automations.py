"""When X happens, do Y -- written by the user, not by a model.

Marvi has had three ways for something to happen on its own: a cron job, a
Composio trigger, and the Mind deciding. All three are Marvi's. What the user
could not do is say "every time *this* happens, do *that*" and have it be
exactly that, every time, with no model in the loop deciding whether today is
different.

An automation is a rule with three parts:

    when    a trigger -- a room event, an account item, a schedule, an app
            taking focus, or a webhook somebody local can call
    if      an optional condition, matched against the event's own fields with
            no model involved, because a rule that sometimes disagrees with
            itself is not a rule
    then    an action: a tool call, with its arguments

## What it may not do

**It runs through the ordinary tool path.** `/tools/{name}` is the only way an
action happens, so Confirm mode still asks, YOLO still does not, the audit log
still records it, and an external write is still deduplicated. An automation is
a way to *ask* for a tool call without typing it, never a way around the rules
that govern one.

**Marvi cannot switch one on.** She can propose one -- "want me to do that
every time?" -- and the proposal lands as a disabled rule the user enables.
A model that can write its own standing instructions is a model that can
quietly grant itself anything.

**A webhook is local and signed.** `POST /hooks/{id}` accepts a request only
with the rule's own secret, from loopback, and the payload it carries is
untrusted data that can fill declared fields and nothing else.
"""

from __future__ import annotations

import hmac
import json
import sqlite3
import threading
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from .logs import get_logger

log = get_logger("gateway")

#: What can set a rule off. Each one is a source Marvi already has.
TRIGGERS = ("schedule", "room", "account", "app_focus", "webhook")

#: How many times one rule may fire in an hour. A webhook nobody rate-limits is
#: a way to make Marvi do something four thousand times.
MAX_PER_HOUR = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS automations (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    trigger    TEXT NOT NULL,
    match      TEXT NOT NULL DEFAULT '{}',
    action     TEXT NOT NULL,
    arguments  TEXT NOT NULL DEFAULT '{}',
    enabled    INTEGER NOT NULL DEFAULT 0,
    secret     TEXT NOT NULL DEFAULT '',
    proposed_by TEXT NOT NULL DEFAULT 'owner',
    created_at TEXT NOT NULL,
    last_run   TEXT NOT NULL DEFAULT '',
    last_result TEXT NOT NULL DEFAULT '',
    runs       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS automation_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    automation_id TEXT NOT NULL REFERENCES automations(id) ON DELETE CASCADE,
    at            TEXT NOT NULL,
    trigger_by    TEXT NOT NULL DEFAULT '',
    ok            INTEGER NOT NULL DEFAULT 0,
    detail        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS automation_runs_one ON automation_runs(automation_id, id);
"""


def default_path() -> Path:
    from .paths import root

    return root() / "automations.sqlite3"


def matches(rule: dict[str, Any], event: dict[str, Any]) -> bool:
    """Whether this event satisfies the rule's condition.

    Plain equality and `in`, deliberately: a condition language with operators
    is a small programming language nobody asked for, and the moment a rule
    needs one it wants a prompt instead.
    """
    try:
        wanted = json.loads(rule.get("match") or "{}")
    except (TypeError, ValueError):
        return False
    if not isinstance(wanted, dict):
        return False
    for field, value in wanted.items():
        seen = event.get(field)
        if isinstance(value, list):
            if seen not in value:
                return False
        elif isinstance(value, str) and isinstance(seen, str):
            if value.lower() not in seen.lower():
                return False
        elif seen != value:
            return False
    return True


def fill(arguments: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Substitute `{field}` in the action's arguments from the event.

    Only declared fields, only as whole values or inside a string: the payload
    is untrusted, so it fills a slot the user wrote and never becomes one.
    """
    filled: dict[str, Any] = {}
    for key, value in (arguments or {}).items():
        if isinstance(value, str):
            for field, seen in event.items():
                value = value.replace("{" + str(field) + "}", str(seen)[:500])
        filled[key] = value
    return filled


class Automations:
    """The rules, and what happened when they fired."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()
        self._lock = threading.Lock()
        #: When each rule last fired, for the rate limit.
        self._recent: dict[str, list[float]] = {}
        #: `(tool, arguments) -> result`. The Gateway supplies the real one so
        #: every action goes through confirmation and the audit log.
        self.call: Any = None

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")

    def add(
        self,
        name: str,
        trigger: str,
        action: str,
        arguments: dict[str, Any] | None = None,
        match: dict[str, Any] | None = None,
        enabled: bool = False,
        proposed_by: str = "owner",
    ) -> dict[str, Any]:
        if trigger not in TRIGGERS:
            raise ValueError(f"unknown trigger {trigger!r}; use one of {', '.join(TRIGGERS)}")
        identifier = uuid4().hex[:12]
        with self._lock:
            self._db.execute(
                "INSERT INTO automations (id, name, trigger, match, action, arguments, enabled,"
                " secret, proposed_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    " ".join((name or "").split())[:120] or "Untitled rule",
                    trigger,
                    json.dumps(match or {}),
                    action,
                    json.dumps(arguments or {}),
                    # A rule Marvi proposed is never on: see the module docstring.
                    1 if (enabled and proposed_by == "owner") else 0,
                    uuid4().hex if trigger == "webhook" else "",
                    proposed_by,
                    self._now(),
                ),
            )
            self._db.commit()
        return self.get(identifier)

    def get(self, rule_id: str) -> dict[str, Any]:
        row = self._db.execute("SELECT * FROM automations WHERE id = ?", (rule_id,)).fetchone()
        if row is None:
            raise KeyError(f"no automation called {rule_id}")
        rule = dict(row)
        rule["match"] = json.loads(rule["match"] or "{}")
        rule["arguments"] = json.loads(rule["arguments"] or "{}")
        rule["enabled"] = bool(rule["enabled"])
        rule["history"] = [
            dict(one)
            for one in self._db.execute(
                "SELECT * FROM automation_runs WHERE automation_id = ? ORDER BY id DESC LIMIT 20",
                (rule_id,),
            )
        ]
        return rule

    def all(self) -> list[dict[str, Any]]:
        return [
            self.get(str(row["id"]))
            for row in self._db.execute("SELECT id FROM automations ORDER BY created_at DESC")
        ]

    def set_enabled(self, rule_id: str, enabled: bool) -> dict[str, Any]:
        self.get(rule_id)
        with self._lock:
            self._db.execute(
                "UPDATE automations SET enabled = ? WHERE id = ?", (1 if enabled else 0, rule_id)
            )
            self._db.commit()
        log.info("automation %s %s", rule_id, "enabled" if enabled else "disabled")
        return self.get(rule_id)

    def remove(self, rule_id: str) -> bool:
        with self._lock:
            gone = self._db.execute("DELETE FROM automations WHERE id = ?", (rule_id,)).rowcount
            self._db.commit()
        return bool(gone)

    # -- firing ---------------------------------------------------------------

    def _too_often(self, rule_id: str) -> bool:
        import time

        now = time.time()
        seen = [when for when in self._recent.get(rule_id, []) if now - when < 3600]
        self._recent[rule_id] = [*seen, now]
        return len(seen) >= MAX_PER_HOUR

    def _record(self, rule_id: str, by: str, ok: bool, detail: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO automation_runs (automation_id, at, trigger_by, ok, detail)"
                " VALUES (?, ?, ?, ?, ?)",
                (rule_id, self._now(), by, 1 if ok else 0, detail[:500]),
            )
            self._db.execute(
                "UPDATE automations SET last_run = ?, last_result = ?, runs = runs + 1"
                " WHERE id = ?",
                (self._now(), detail[:200], rule_id),
            )
            self._db.commit()

    def fire(self, trigger: str, event: dict[str, Any], rule_id: str = "") -> list[dict[str, Any]]:
        """Run every enabled rule this event satisfies. Returns what happened."""
        done: list[dict[str, Any]] = []
        for rule in self.all():
            if rule_id and rule["id"] != rule_id:
                continue
            if not rule["enabled"] or rule["trigger"] != trigger:
                continue
            if not matches({"match": json.dumps(rule["match"])}, event):
                continue
            if self._too_often(rule["id"]):
                self._record(
                    rule["id"], trigger, False,
                    f"rate limited: more than {MAX_PER_HOUR} times in an hour",
                )
                done.append({"id": rule["id"], "ok": False, "detail": "rate limited"})
                continue
            if self.call is None:
                self._record(rule["id"], trigger, False, "no tool router is connected")
                continue
            arguments = fill(rule["arguments"], event)
            try:
                result = self.call(rule["action"], arguments)
                detail = str(result)[:300]
                ok = True
            except Exception as exc:
                detail, ok = f"{type(exc).__name__}: {exc}"[:300], False
            self._record(rule["id"], trigger, ok, detail)
            done.append({"id": rule["id"], "name": rule["name"], "ok": ok, "detail": detail})
        return done

    def by_secret(self, rule_id: str, secret: str) -> dict[str, Any] | None:
        """The webhook rule this request is for, if the secret is right."""
        try:
            rule = self.get(rule_id)
        except KeyError:
            return None
        if rule["trigger"] != "webhook" or not rule["secret"]:
            return None
        # Constant time: a webhook secret is a credential, and an early return
        # on the first wrong byte is a way to guess it.
        return rule if hmac.compare_digest(str(rule["secret"]), str(secret or "")) else None

    def close(self) -> None:
        self._db.close()


def signature(secret: str, body: bytes) -> str:
    """What a caller should send in `x-marvi-signature`, for a caller that can."""
    return hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()
