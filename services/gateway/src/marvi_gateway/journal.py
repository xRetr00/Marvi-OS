"""The durable event journal.

Everything that could make Marvi act arrives here first: room transitions,
account items, scheduled ticks, and memory reflections. The mind reads from the
journal rather than from any live source, which is what makes a decision
reproducible — you can look at exactly the event that caused it.

Two properties matter:

* an event is recorded with its provenance and trust, so the mind can never
  mistake an email for an instruction (REAL-AGENCY condition 1);
* the same event arriving twice is one event, so a poll that overlaps a
  previous poll cannot produce two proposals (condition 2).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEDUPE_WINDOW_SECONDS = 6 * 60 * 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    at           TEXT NOT NULL,
    source       TEXT NOT NULL,
    kind         TEXT NOT NULL,
    summary      TEXT NOT NULL,
    payload      TEXT NOT NULL DEFAULT '{}',
    trusted      INTEGER NOT NULL DEFAULT 0,
    fingerprint  TEXT NOT NULL,
    processed_at TEXT,
    decision_id  INTEGER
);
CREATE INDEX IF NOT EXISTS events_pending ON events(processed_at);
CREATE INDEX IF NOT EXISTS events_fingerprint ON events(fingerprint);

CREATE TABLE IF NOT EXISTS decisions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    event_id    INTEGER,
    trigger     TEXT NOT NULL,
    surface     TEXT NOT NULL,
    rule        TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    provider    TEXT NOT NULL DEFAULT 'deterministic',
    latency_ms  REAL NOT NULL DEFAULT 0,
    tokens      INTEGER NOT NULL DEFAULT 0,
    outcome     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS decisions_at ON decisions(at);
"""


def default_journal_path() -> Path:
    configured = os.environ.get("MARVI_JOURNAL_DB")
    if configured:
        return Path(configured)
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(root) / "Marvi OS" / "journal.sqlite3"


def fingerprint(source: str, kind: str, summary: str, payload: dict[str, Any]) -> str:
    """Identity of an event, independent of when it was seen."""
    provider_id = payload.get("id") or payload.get("provider_id")
    basis = f"{source}|{kind}|{provider_id or summary}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


class EventJournal:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_journal_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        # Journals written before the budget moved from dollars to tokens have a
        # `cost` column and no `tokens` one. Old rows keep their history; they
        # just count as zero thinking, which is the harmless direction.
        columns = {r["name"] for r in self._db.execute("PRAGMA table_info(decisions)")}
        if "tokens" not in columns:
            self._db.execute("ALTER TABLE decisions ADD COLUMN tokens INTEGER NOT NULL DEFAULT 0")
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # -- writing ------------------------------------------------------------

    def append(
        self,
        source: str,
        kind: str,
        summary: str,
        payload: dict[str, Any] | None = None,
        trusted: bool = False,
        now: datetime | None = None,
    ) -> int | None:
        """Record an event. Returns None when it is a duplicate."""
        body = payload or {}
        mark = fingerprint(source, kind, summary, body)
        moment = now or datetime.now(UTC)

        recent = self._db.execute(
            "SELECT id, at FROM events WHERE fingerprint = ? ORDER BY id DESC LIMIT 1", (mark,)
        ).fetchone()
        if recent is not None:
            try:
                age = (moment - datetime.fromisoformat(recent["at"])).total_seconds()
            except ValueError:
                age = 0.0
            if age < DEDUPE_WINDOW_SECONDS:
                return None

        cursor = self._db.execute(
            "INSERT INTO events (at, source, kind, summary, payload, trusted, fingerprint)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                moment.isoformat(),
                source,
                kind,
                summary[:300],
                json.dumps(body, default=str)[:8_000],
                1 if trusted else 0,
                mark,
            ),
        )
        self._db.commit()
        return int(cursor.lastrowid or 0)

    # -- reading ------------------------------------------------------------

    @staticmethod
    def _event(row: sqlite3.Row) -> dict[str, Any]:
        try:
            payload = json.loads(row["payload"])
        except ValueError:
            payload = {}
        return {
            "id": row["id"],
            "at": row["at"],
            "source": row["source"],
            "kind": row["kind"],
            "summary": row["summary"],
            "payload": payload,
            "trusted": bool(row["trusted"]),
        }

    def pending(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM events WHERE processed_at IS NULL ORDER BY id LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
        return [self._event(r) for r in rows]

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)
        ).fetchall()
        return [self._event(r) for r in rows]

    def count_pending(self) -> int:
        return int(
            self._db.execute(
                "SELECT COUNT(*) n FROM events WHERE processed_at IS NULL"
            ).fetchone()["n"]
        )

    def mark_processed(self, event_id: int, decision_id: int | None = None) -> None:
        self._db.execute(
            "UPDATE events SET processed_at = ?, decision_id = ? WHERE id = ?",
            (datetime.now(UTC).isoformat(), decision_id, event_id),
        )
        self._db.commit()

    # -- decisions ----------------------------------------------------------

    def record_decision(
        self,
        trigger: str,
        surface: str,
        rule: str,
        detail: str = "",
        event_id: int | None = None,
        provider: str = "deterministic",
        latency_ms: float = 0.0,
        tokens: int = 0,
        outcome: str = "",
        now: datetime | None = None,
    ) -> int:
        cursor = self._db.execute(
            "INSERT INTO decisions"
            " (at, event_id, trigger, surface, rule, detail, provider, latency_ms, tokens, outcome)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (now or datetime.now(UTC)).isoformat(),
                event_id,
                trigger[:200],
                surface,
                rule,
                detail[:500],
                provider,
                latency_ms,
                tokens,
                outcome[:300],
            ),
        )
        self._db.commit()
        return int(cursor.lastrowid or 0)

    def decisions(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)
        ).fetchall()
        return [dict(r) for r in rows]

    def tokens_since(self, since: datetime) -> int:
        row = self._db.execute(
            "SELECT COALESCE(SUM(tokens), 0) AS total FROM decisions WHERE at >= ?",
            (since.isoformat(),),
        ).fetchone()
        return int(row["total"])

    def last_surfaced(self, source: str, kind: str) -> datetime | None:
        """When Marvi last actually surfaced something for this source/kind."""
        row = self._db.execute(
            "SELECT d.at FROM decisions d JOIN events e ON e.id = d.event_id"
            " WHERE e.source = ? AND e.kind = ? AND d.surface != 'silent'"
            " ORDER BY d.id DESC LIMIT 1",
            (source, kind),
        ).fetchone()
        if row is None:
            return None
        try:
            return datetime.fromisoformat(row["at"])
        except ValueError:
            return None
