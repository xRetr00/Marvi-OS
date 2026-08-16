"""Durable local memory.

Episodic entries are things that happened; semantic entries are things that
are true. Both live in one SQLite file with an FTS5 index — stdlib, no server,
no vector database, no embedding model, and no outbound telemetry.

Provenance is the part that matters. A memory derived from an email or a web
page is still that email talking. It is stored with `trusted = 0` and is
re-enveloped on recall, so a prompt injection cannot launder itself into
instruction position by taking a detour through memory.

See docs/DECISIONS.md ADR-014 for why an upstream memory framework was not
adopted here.
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .untrusted import wrap_external

MemoryKind = Literal["episodic", "semantic"]
DEFAULT_SEARCH_LIMIT = 10
MAX_BODY_CHARS = 4_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    kind     TEXT NOT NULL,
    subject  TEXT NOT NULL,
    body     TEXT NOT NULL,
    source   TEXT NOT NULL DEFAULT 'marvi',
    trusted  INTEGER NOT NULL DEFAULT 1,
    at       TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
    USING fts5(subject, body, content='memories', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, subject, body) VALUES (new.id, new.subject, new.body);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, subject, body)
        VALUES ('delete', old.id, old.subject, old.body);
END;
"""


def default_memory_path() -> Path:
    configured = os.environ.get("MARVI_MEMORY_DB")
    if configured:
        return Path(configured)
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(root) / "Marvi OS" / "memory.sqlite3"


def _fts_query(text: str) -> str:
    """Quote every term so user text can never be FTS5 operator syntax."""
    terms = [t for t in re.findall(r"[\w']+", text) if t]
    return " OR ".join(f'"{t}"' for t in terms)


class MemoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_memory_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # -- writing ------------------------------------------------------------

    def remember(
        self,
        subject: str,
        body: str,
        kind: MemoryKind = "episodic",
        source: str = "marvi",
        trusted: bool = True,
    ) -> int:
        if not subject.strip():
            raise ValueError("a memory needs a subject")
        cursor = self._db.execute(
            "INSERT INTO memories (kind, subject, body, source, trusted, at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                kind,
                subject.strip()[:200],
                body[:MAX_BODY_CHARS],
                source,
                1 if trusted else 0,
                datetime.now(UTC).isoformat(),
            ),
        )
        self._db.commit()
        return int(cursor.lastrowid or 0)

    def remember_external(self, subject: str, body: str, source: str, **kwargs: Any) -> int:
        """Anything originating outside this machine is never stored as trusted."""
        return self.remember(subject, body, source=source, trusted=False, **kwargs)

    # -- reading ------------------------------------------------------------

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        entry = {
            "id": row["id"],
            "kind": row["kind"],
            "subject": row["subject"],
            "body": row["body"],
            "source": row["source"],
            "trusted": bool(row["trusted"]),
            "at": row["at"],
        }
        if not entry["trusted"]:
            # Recall must not strip the boundary the content arrived with.
            entry["body"] = wrap_external(entry["source"], entry["body"]).text
        return entry

    def search(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[dict[str, Any]]:
        match = _fts_query(query)
        if not match:
            return []
        rows = self._db.execute(
            "SELECT m.* FROM memories_fts f JOIN memories m ON m.id = f.rowid"
            " WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
            (match, max(1, min(limit, 100))),
        ).fetchall()
        return [self._row(row) for row in rows]

    def recent(self, limit: int = DEFAULT_SEARCH_LIMIT, kind: MemoryKind | None = None) -> list[dict[str, Any]]:
        if kind:
            rows = self._db.execute(
                "SELECT * FROM memories WHERE kind = ? ORDER BY id DESC LIMIT ?",
                (kind, max(1, min(limit, 100))),
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM memories ORDER BY id DESC LIMIT ?", (max(1, min(limit, 100)),)
            ).fetchall()
        return [self._row(row) for row in rows]

    def count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"])

    # -- forgetting and export ----------------------------------------------

    def forget(self, memory_id: int) -> bool:
        cursor = self._db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._db.commit()
        return cursor.rowcount > 0

    def forget_matching(self, query: str) -> int:
        ids = [entry["id"] for entry in self.search(query, limit=100)]
        if not ids:
            return 0
        self._db.executemany("DELETE FROM memories WHERE id = ?", [(i,) for i in ids])
        self._db.commit()
        return len(ids)

    def forget_all(self) -> int:
        removed = self.count()
        self._db.execute("DELETE FROM memories")
        self._db.commit()
        return removed

    def export(self) -> list[dict[str, Any]]:
        """Everything, verbatim and unenveloped — this is the user's own data
        leaving on their instruction, not content being fed to a model."""
        rows = self._db.execute("SELECT * FROM memories ORDER BY id").fetchall()
        return [
            {
                "id": r["id"],
                "kind": r["kind"],
                "subject": r["subject"],
                "body": r["body"],
                "source": r["source"],
                "trusted": bool(r["trusted"]),
                "at": r["at"],
            }
            for r in rows
        ]

    def world_summary(self, limit: int = 5) -> dict[str, Any]:
        """A small, cheap current-world line. No model call."""
        facts = self.recent(limit=limit, kind="semantic")
        events = self.recent(limit=limit, kind="episodic")
        return {
            "total": self.count(),
            "facts": [f["subject"] for f in facts],
            "recent_events": [e["subject"] for e in events],
        }


def register_memory_tools(registry, memory: MemoryStore) -> None:
    from .tools import ToolSpec

    def memory_remember(subject: str, body: str) -> dict[str, Any]:
        return {"id": memory.remember(subject, body, kind="semantic")}

    def memory_search(query: str) -> dict[str, Any]:
        return {"results": memory.search(query)}

    def memory_forget(query: str) -> dict[str, Any]:
        return {"forgotten": memory.forget_matching(query)}

    registry.register(
        ToolSpec(
            name="memory_remember",
            description="Remember a durable fact",
            arguments={"subject": str, "body": str},
            sensitive=False,
            handler=memory_remember,
        )
    )
    registry.register(
        ToolSpec(
            name="memory_search",
            description="Search what Marvi remembers",
            arguments={"query": str},
            sensitive=False,
            handler=memory_search,
        )
    )
    registry.register(
        ToolSpec(
            name="memory_forget",
            description="Forget everything matching a phrase",
            arguments={"query": str},
            sensitive=True,
            handler=memory_forget,
        )
    )
