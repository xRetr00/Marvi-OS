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

import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from .logs import get_logger
from .untrusted import wrap_external

log = get_logger("memory")

MemoryKind = Literal["episodic", "semantic"]
GraphMode = Literal["tree", "contacts"]
DEFAULT_SEARCH_LIMIT = 10
MAX_BODY_CHARS = 4_000

#: How alike two semantic facts must be before one is treated as correcting the
#: other rather than joining it.
#:
#: Measured as containment -- the shared significant words over the *smaller*
#: set -- rather than as Jaccard, because a correction routinely adds words the
#: original did not have. "The user's name is Sheriff (one F)" carries two
#: qualifiers the first version lacked, and counting those against the match
#: broke the chain: the real four-step correction ended as two memories instead
#: of one, which is the bug in miniature.
#:
#: Not weaker than Jaccard here, because `MIN_WORDS_TO_SUPERSEDE` already rules
#: out the short statements containment would over-match. Checked against the
#: case it must not break: "the user's name is X, developer of Marvi" against
#: "the user's brother is Y, developer of Marvi" scores 0.5 and stays two facts.
SUPERSEDE_SIMILARITY = 0.7

#: A statement shorter than this is not judged. "Likes tea" and "likes coffee"
#: share almost every word and mean the opposite.
MIN_WORDS_TO_SUPERSEDE = 4

#: How far back to look. Recent facts are the ones being corrected; a scan of
#: the whole store on every write is a table scan on the hot path.
SUPERSEDE_SCAN = 50

#: Words too common to carry meaning. Without this, every sentence about the
#: user overlaps every other one on "the", "is" and "they".
_COMMON = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
        "have", "he", "her", "him", "his", "in", "is", "it", "its", "of", "on",
        "or", "she", "that", "the", "their", "them", "they", "this", "to",
        "user", "was", "were", "with", "you", "your",
    }
)


def _significant(text: str) -> set[str]:
    """The words of a statement that carry its meaning."""
    return {
        word
        for word in re.findall(r"[a-z0-9]+", (text or "").lower())
        if word not in _COMMON and len(word) > 1
    }


# Consolidation defaults. Deliberately conservative: forgetting the user's
# own data is worse than keeping a little too much.
EPISODIC_TTL_DAYS = 45
PROMOTE_AFTER_REPEATS = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    kind      TEXT NOT NULL,
    subject   TEXT NOT NULL,
    body      TEXT NOT NULL,
    source    TEXT NOT NULL DEFAULT 'marvi',
    trusted   INTEGER NOT NULL DEFAULT 1,
    at        TEXT NOT NULL,
    strength  INTEGER NOT NULL DEFAULT 1,
    last_used TEXT
);
CREATE TABLE IF NOT EXISTS entities (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'thing',
    at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    predicate  TEXT NOT NULL,
    object_id  INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    source     TEXT NOT NULL DEFAULT 'marvi',
    trusted    INTEGER NOT NULL DEFAULT 1,
    at         TEXT NOT NULL,
    UNIQUE (subject_id, predicate, object_id)
);
CREATE INDEX IF NOT EXISTS relations_subject ON relations(subject_id);
CREATE INDEX IF NOT EXISTS relations_object ON relations(object_id);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
    USING fts5(subject, body, content='memories', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, subject, body) VALUES (new.id, new.subject, new.body);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, subject, body)
        VALUES ('delete', old.id, old.subject, old.body);
END;
-- Corrections rewrite a row in place, and an external-content FTS5 index does
-- not follow an UPDATE on its own. Without this, `memory_search` would go on
-- matching the text a memory used to hold -- which is the duplicate problem
-- again, hidden one layer down where nobody would look for it.
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, subject, body)
        VALUES ('delete', old.id, old.subject, old.body);
    INSERT INTO memories_fts(rowid, subject, body)
        VALUES (new.id, new.subject, new.body);
END;
"""


def default_memory_path() -> Path:
    from .paths import memory_db

    return memory_db()


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
        """Store a fact, replacing one it corrects rather than sitting beside it.

        `INSERT` was the whole implementation, and a store that only inserts
        cannot be corrected -- only added to. What that looked like in practice,
        over two minutes of one conversation:

            #20  The user's name is Sheriff and they are the developer of Marvi.
            #21  The user's name is Sheriff (one F), and they are the developer.
            #22  The user's name is Shrif, and they are the developer of Marvi.
            #23  The user's name is Shreef (spelled S-H-R-E-E-F), ...
            #24  The user's name is Shreef, spelled S-H-E-R-E-E-F, ...

        Five memories, one fact, five spellings -- because the recogniser hears
        a name differently each time and every correction was stored as an
        additional truth. Recall then returns all five, and the most recent is
        not distinguishable from the four it was meant to replace.

        Keying on the subject alone would not have caught it: the subjects were
        `Sheriff`, `Shrif` and `Shreef`, which is the same drift one level up.
        So the match is on what the fact *says* -- see `_supersedes`.

        Only semantic memories supersede. An episodic one is a record of a
        moment and two of those are not a contradiction; they are two moments.
        """
        if not subject.strip():
            raise ValueError("a memory needs a subject")
        if kind == "semantic" and (previous := self._supersedes(body, source, trusted)):
            return self._replace(previous, subject, body, kind, source, trusted)
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
        memory_id = int(cursor.lastrowid or 0)
        log.info(
            "memory stored",
            extra={
                "marvi_memory_id": memory_id,
                "marvi_kind": kind,
                "marvi_source": source,
                "marvi_trusted": trusted,
                "marvi_subject_chars": len(subject.strip()),
                "marvi_body_chars": min(len(body), MAX_BODY_CHARS),
            },
        )
        return memory_id

    def _supersedes(self, body: str, source: str, trusted: bool) -> int | None:
        """The id of the fact this one corrects, or None if it is new.

        Matched on the *shape* of the statement rather than on the subject,
        because the subject is the model's guess and it drifted with every
        mishearing. What did not drift is the sentence: "the user's name is X
        and they are the developer of Marvi", five times over.

        So: two semantic facts are the same fact when the significant words of
        the shorter one are mostly inside the longer. The words that differ are
        the correction.

        Deliberately conservative. Merging two facts that are merely related
        loses one of them silently, which is worse than the duplication this
        exists to stop -- so the bar is high, and a fact that clears it is one
        a person would read as a restatement.
        """
        words = _significant(body)
        if len(words) < MIN_WORDS_TO_SUPERSEDE:
            # Too short to judge. "Likes tea" and "likes coffee" share almost
            # everything and mean the opposite.
            return None
        for row in self._db.execute(
            "SELECT id, body FROM memories WHERE kind = 'semantic' AND source = ?"
            " AND trusted = ? ORDER BY id DESC LIMIT ?",
            (source, 1 if trusted else 0, SUPERSEDE_SCAN),
        ):
            against = _significant(row["body"])
            if not against:
                continue
            overlap = len(words & against) / min(len(words), len(against))
            if overlap >= SUPERSEDE_SIMILARITY:
                return int(row["id"])
        return None

    def _replace(
        self, memory_id: int, subject: str, body: str, kind: str, source: str, trusted: bool
    ) -> int:
        """Overwrite a fact in place, keeping its id.

        In place rather than delete-and-insert so anything already pointing at
        this memory keeps pointing at the corrected version rather than at a
        hole.
        """
        self._db.execute(
            "UPDATE memories SET kind = ?, subject = ?, body = ?, source = ?,"
            " trusted = ?, at = ? WHERE id = ?",
            (
                kind,
                subject.strip()[:200],
                body[:MAX_BODY_CHARS],
                source,
                1 if trusted else 0,
                datetime.now(UTC).isoformat(),
                memory_id,
            ),
        )
        self._db.commit()
        log.info(
            "memory corrected in place",
            extra={
                "marvi_memory_id": memory_id,
                "marvi_subject": subject.strip()[:80],
                "marvi_body_chars": min(len(body), MAX_BODY_CHARS),
            },
        )
        return memory_id

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
        found = [self._row(row) for row in rows]
        self.reinforce([entry["id"] for entry in found])
        log.info(
            "memory search completed",
            extra={
                "marvi_query_chars": len(query),
                "marvi_limit": max(1, min(limit, 100)),
                "marvi_results": len(found),
            },
        )
        return found

    def recent(
        self, limit: int = DEFAULT_SEARCH_LIMIT, kind: MemoryKind | None = None
    ) -> list[dict[str, Any]]:
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
        removed = cursor.rowcount > 0
        log.info(
            "memory deleted by id",
            extra={"marvi_memory_id": memory_id, "marvi_removed": removed},
        )
        return removed

    def forget_matching(self, query: str) -> int:
        ids = [entry["id"] for entry in self.search(query, limit=100)]
        if not ids:
            return 0
        self._db.executemany("DELETE FROM memories WHERE id = ?", [(i,) for i in ids])
        self._db.commit()
        log.info(
            "memory deleted by query",
            extra={"marvi_query_chars": len(query), "marvi_removed": len(ids)},
        )
        return len(ids)

    def forget_all(self) -> int:
        removed = self.count()
        self._db.execute("DELETE FROM memories")
        self._db.commit()
        log.warning("all memories deleted", extra={"marvi_removed": removed})
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

    # -- reinforcement ------------------------------------------------------

    def reinforce(self, memory_ids: list[int]) -> None:
        """Recall strengthens a memory.

        Consolidation reads this to decide what survives, so genuinely useful
        memories outlive noise without anyone hand-tuning a policy.
        """
        if not memory_ids:
            return
        now = datetime.now(UTC).isoformat()
        self._db.executemany(
            "UPDATE memories SET strength = strength + 1, last_used = ? WHERE id = ?",
            [(now, i) for i in memory_ids],
        )
        self._db.commit()

    # -- knowledge graph ----------------------------------------------------

    def _entity_id(self, name: str, kind: str = "thing") -> int:
        clean = name.strip()[:120]
        if not clean:
            raise ValueError("an entity needs a name")
        row = self._db.execute("SELECT id FROM entities WHERE name = ?", (clean,)).fetchone()
        if row:
            return int(row["id"])
        cursor = self._db.execute(
            "INSERT INTO entities (name, kind, at) VALUES (?, ?, ?)",
            (clean, kind, datetime.now(UTC).isoformat()),
        )
        return int(cursor.lastrowid or 0)

    def link(
        self,
        subject: str,
        predicate: str,
        obj: str,
        source: str = "marvi",
        trusted: bool = True,
    ) -> int:
        """Record subject -[predicate]-> object.

        Re-stating a known fact is not a duplicate; the unique constraint
        collapses it instead of growing the graph.
        """
        if not predicate.strip():
            raise ValueError("a relation needs a predicate")
        subject_id = self._entity_id(subject)
        object_id = self._entity_id(obj)
        predicate = predicate.strip()[:80]
        self._db.execute(
            "INSERT OR IGNORE INTO relations"
            " (subject_id, predicate, object_id, source, trusted, at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                subject_id,
                predicate,
                object_id,
                source,
                1 if trusted else 0,
                datetime.now(UTC).isoformat(),
            ),
        )
        self._db.commit()
        row = self._db.execute(
            "SELECT id FROM relations WHERE subject_id = ? AND predicate = ? AND object_id = ?",
            (subject_id, predicate, object_id),
        ).fetchone()
        relation_id = int(row["id"]) if row else 0
        log.info(
            "memory relation stored",
            extra={
                "marvi_relation_id": relation_id,
                "marvi_source": source,
                "marvi_trusted": trusted,
            },
        )
        return relation_id

    def neighbours(self, name: str, limit: int = 25) -> list[dict[str, Any]]:
        """Everything one hop from an entity, in either direction."""
        clean = name.strip()
        rows = self._db.execute(
            "SELECT s.name AS subject, r.predicate, o.name AS object, r.trusted, r.source"
            " FROM relations r"
            " JOIN entities s ON s.id = r.subject_id"
            " JOIN entities o ON o.id = r.object_id"
            " WHERE s.name = ? COLLATE NOCASE OR o.name = ? COLLATE NOCASE"
            " ORDER BY r.id DESC LIMIT ?",
            (clean, clean, max(1, min(limit, 200))),
        ).fetchall()
        return [
            {
                "subject": r["subject"],
                "predicate": r["predicate"],
                "object": r["object"],
                "trusted": bool(r["trusted"]),
                "source": r["source"],
            }
            for r in rows
        ]

    def graph_size(self) -> dict[str, int]:
        return {
            "entities": int(self._db.execute("SELECT COUNT(*) n FROM entities").fetchone()["n"]),
            "relations": int(self._db.execute("SELECT COUNT(*) n FROM relations").fetchone()["n"]),
        }

    def graph_export(self, mode: GraphMode = "tree", limit: int = 1000) -> dict[str, Any]:
        """Project the local store into the renderer's read-only ARC graph.

        This is deliberately a projection, not a second persistence model.  The
        tree view groups memories beneath their provenance source; the contacts
        view exposes the explicit entity relationships already held by Marvi.
        Nothing in the renderer gets direct SQLite access or authority to
        mutate memory.
        """
        if mode not in ("tree", "contacts"):
            raise ValueError(f"unsupported graph mode: {mode}")
        bounded = max(1, min(int(limit), 2_000))
        if mode == "contacts":
            entities = self._db.execute(
                "SELECT id, name, kind FROM entities ORDER BY id DESC LIMIT ?", (bounded,)
            ).fetchall()
            entity_ids = {int(row["id"]) for row in entities}
            nodes = [
                {
                    "id": f"entity:{row['id']}",
                    "kind": "contact",
                    "label": row["name"],
                    "entity_kind": row["kind"],
                }
                for row in entities
            ]
            relations = self._db.execute(
                "SELECT id, subject_id, predicate, object_id, source, trusted"
                " FROM relations ORDER BY id DESC LIMIT ?",
                (bounded,),
            ).fetchall()
            edges = [
                {
                    "id": f"relation:{row['id']}",
                    "source": f"entity:{row['subject_id']}",
                    "target": f"entity:{row['object_id']}",
                    "label": row["predicate"],
                    "trusted": bool(row["trusted"]),
                    "provenance": row["source"],
                }
                for row in relations
                if int(row["subject_id"]) in entity_ids and int(row["object_id"]) in entity_ids
            ]
            return {"mode": mode, "nodes": nodes, "edges": edges}

        rows = self._db.execute(
            "SELECT id, kind, subject, source, trusted, at FROM memories ORDER BY id DESC LIMIT ?",
            (bounded,),
        ).fetchall()
        if not rows:
            return {"mode": mode, "nodes": [], "edges": []}
        sources = sorted({str(row["source"]) for row in rows})
        nodes: list[dict[str, Any]] = [
            {"id": "arc:memory", "kind": "root", "label": "Memory", "level": 2}
        ]
        edges: list[dict[str, Any]] = []
        for source in sources:
            source_id = f"source:{source}"
            nodes.append({"id": source_id, "kind": "source", "label": source, "level": 1})
            edges.append({"id": f"arc:{source_id}", "source": "arc:memory", "target": source_id})
        for row in rows:
            node_id = f"memory:{row['id']}"
            source_id = f"source:{row['source']}"
            nodes.append(
                {
                    "id": node_id,
                    "kind": "summary" if row["kind"] == "semantic" else "chunk",
                    "label": row["subject"],
                    "level": 0,
                    "memory_kind": row["kind"],
                    "trusted": bool(row["trusted"]),
                    "provenance": row["source"],
                    "at": row["at"],
                }
            )
            edges.append({"id": f"arc:{node_id}", "source": source_id, "target": node_id})
        return {"mode": mode, "nodes": nodes, "edges": edges}

    def forget_entity(self, name: str) -> int:
        """Deleting an entity takes its relations with it."""
        self._db.execute("PRAGMA foreign_keys = ON")
        cursor = self._db.execute(
            "DELETE FROM entities WHERE name = ? COLLATE NOCASE", (name.strip(),)
        )
        self._db.commit()
        return cursor.rowcount

    # -- reflection and consolidation ---------------------------------------

    def reflect(self, summarise: Any = None, limit: int = 50) -> dict[str, Any]:
        """Turn repeated episodes into durable facts.

        The default pass is deterministic and costs nothing: a subject seen
        PROMOTE_AFTER_REPEATS times becomes a semantic fact. `summarise` is the
        seam for an LLM pass -- it receives the grouped episodes and returns
        [(subject, body)]. It stays optional on purpose, because
        REAL-AGENCY.md requires a no-op reflection to be cheap and normal.
        """
        rows = self._db.execute(
            "SELECT subject, COUNT(*) AS n FROM memories WHERE kind = 'episodic'"
            " GROUP BY subject HAVING n >= ? ORDER BY n DESC LIMIT ?",
            (PROMOTE_AFTER_REPEATS, max(1, min(limit, 200))),
        ).fetchall()
        groups = [{"subject": r["subject"], "count": int(r["n"])} for r in rows]

        promoted: list[str] = []
        if summarise is not None:
            summarised = summarise(groups) or []
            for subject, body in summarised:
                self.remember(subject, body, kind="semantic", source="reflection")
                promoted.append(subject)
            if promoted:
                log.info(
                    "memory reflection completed with auxiliary model",
                    extra={
                        "marvi_considered": len(groups),
                        "marvi_promoted": len(promoted),
                        "marvi_route": "auxiliary/memory",
                    },
                )
                return {"considered": len(groups), "promoted": promoted}
            # A missing/cooling/malformed Auxiliary model must not disable the
            # deterministic reflection that existed before the model seam.
            log.info(
                "auxiliary memory reflection returned no facts; using deterministic pass",
                extra={"marvi_considered": len(groups), "marvi_route": "auxiliary/memory"},
            )

        for group in groups:
            already = self._db.execute(
                "SELECT id FROM memories WHERE kind = 'semantic' AND subject = ?",
                (group["subject"][:200],),
            ).fetchone()
            if already:
                continue
            self.remember(
                group["subject"],
                f"Recurs: seen {group['count']} times.",
                kind="semantic",
                source="reflection",
            )
            promoted.append(group["subject"])
        log.info(
            "memory reflection completed deterministically",
            extra={"marvi_considered": len(groups), "marvi_promoted": len(promoted)},
        )
        return {"considered": len(groups), "promoted": promoted}

    def consolidate(self, now: datetime | None = None) -> dict[str, int]:
        """The sleep pass: drop stale, unreinforced episodes.

        Semantic facts and anything ever recalled are never dropped -- a memory
        the user actually used is not noise.
        """
        moment = now or datetime.now(UTC)
        cutoff = (moment - timedelta(days=EPISODIC_TTL_DAYS)).isoformat()
        forgotten = self._db.execute(
            "DELETE FROM memories WHERE kind = 'episodic' AND at < ?"
            " AND strength <= 1 AND last_used IS NULL",
            (cutoff,),
        ).rowcount
        orphans = self._db.execute(
            "DELETE FROM entities WHERE id NOT IN"
            " (SELECT subject_id FROM relations UNION SELECT object_id FROM relations)"
        ).rowcount
        self._db.commit()
        log.info(
            "memory consolidation completed",
            extra={"marvi_forgotten": forgotten, "marvi_orphan_entities": orphans},
        )
        return {"forgotten": forgotten, "orphan_entities": orphans}

    def world_summary(self, limit: int = 5) -> dict[str, Any]:
        """A small, cheap current-world line. No model call."""
        facts = self.recent(limit=limit, kind="semantic")
        events = self.recent(limit=limit, kind="episodic")
        return {
            "total": self.count(),
            "facts": [f["subject"] for f in facts],
            "recent_events": [e["subject"] for e in events],
            "graph": self.graph_size(),
        }


def register_memory_tools(registry, memory: MemoryStore, summarise: Any = None) -> None:
    from .tools import ToolSpec

    def memory_remember(subject: str, body: str) -> dict[str, Any]:
        return {"id": memory.remember(subject, body, kind="semantic")}

    def memory_search(query: str) -> dict[str, Any]:
        return {"results": memory.search(query)}

    def memory_recall(query: str) -> dict[str, Any]:
        """Canonical read tool shared by typed chat, voice and MCP clients.

        Keep the older search name as a compatibility alias; recall names the
        agent behaviour and makes the capability discoverable in `/tools`.
        """
        results = memory.search(query)
        return {"query": query, "results": results}

    def memory_forget(query: str) -> dict[str, Any]:
        return {"forgotten": memory.forget_matching(query)}

    def memory_link(subject: str, predicate: str, target: str) -> dict[str, Any]:
        return {"id": memory.link(subject, predicate, target)}

    def memory_neighbours(name: str) -> dict[str, Any]:
        return {"relations": memory.neighbours(name)}

    def memory_reflect() -> dict[str, Any]:
        # The seam has been here since reflection was written and nothing was
        # ever passed into it, so consolidation was whatever repeated often
        # enough and nothing else. A model reads the repeated subjects and
        # writes what is actually true about them; without one, the count-based
        # promotion runs exactly as before.
        return memory.reflect(summarise=summarise)

    registry.register(
        ToolSpec(
            name="memory_remember",
            description="Remember a durable fact",
            arguments={"subject": str, "body": str},
            describes={
                "subject": "What the fact is about, in a word or two. Used to find it later.",
                "body": "The fact itself, in one sentence, in the third person.",
            },
            sensitive=False,
            handler=memory_remember,
        )
    )
    registry.register(
        ToolSpec(
            name="memory_recall",
            description=(
                "Recall durable memories relevant to a person, topic, or past event. "
                "Use this when earlier context may affect the answer."
            ),
            arguments={"query": str},
            describes={"query": "Person, topic, fact, or past event to remember."},
            sensitive=False,
            handler=memory_recall,
        )
    )
    registry.register(
        ToolSpec(
            name="memory_search",
            description="Compatibility alias for memory_recall",
            arguments={"query": str},
            describes={"query": "Words to look for. Plain phrasing, not a search syntax."},
            sensitive=False,
            handler=memory_search,
        )
    )
    registry.register(
        ToolSpec(
            name="memory_forget",
            description="Forget everything matching a phrase",
            arguments={"query": str},
            describes={
                "query": ("Phrase to match. Everything matching it is deleted, so be specific.")
            },
            sensitive=True,
            handler=memory_forget,
        )
    )
    registry.register(
        ToolSpec(
            name="memory_link",
            description="Record a relationship between two things",
            arguments={"subject": str, "predicate": str, "target": str},
            describes={
                "subject": "The thing the relationship starts from.",
                "predicate": "The relationship, as a short verb phrase, e.g. 'works at'.",
                "target": "The thing the relationship points to.",
            },
            sensitive=False,
            handler=memory_link,
        )
    )
    registry.register(
        ToolSpec(
            name="memory_neighbours",
            description="Read what is connected to something",
            arguments={"name": str},
            describes={"name": "The subject or target whose connections to read."},
            sensitive=False,
            handler=memory_neighbours,
        )
    )
    registry.register(
        ToolSpec(
            name="memory_reflect",
            description="Consolidate repeated episodes into durable facts",
            arguments={},
            sensitive=False,
            handler=memory_reflect,
        )
    )
