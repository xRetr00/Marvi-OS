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

import math
import re
import sqlite3
import struct
from datetime import UTC, datetime, timedelta
from itertools import zip_longest
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


#: Below this, a memory is not about the query, and returning it is worse than
#: returning nothing.
#:
#: Measured on this machine with the default model rather than picked as a
#: round number. With bge-small, unrelated text lands at 0.41-0.48 and a real
#: answer at 0.55 or above. An absolute 0.3 would have returned every memory
#: for every query -- "photosynthesis" scores 0.48 against a note about coffee.
#:
#: Model-specific, deliberately. Changing the embedding model means measuring
#: this again; a number that means something different for every model means
#: nothing.
SIMILAR_ENOUGH = 0.52


def _normalise(vector: list[float]) -> list[float]:
    """Unit length, so a dot product is a cosine.

    Done once on the way in rather than on every comparison: a search over a
    few hundred memories would otherwise compute the same magnitudes again for
    each one.
    """
    total = math.sqrt(sum(value * value for value in vector))
    return [value / total for value in vector] if total else list(vector)


def _to_blob(vector: list[float]) -> bytes:
    """float32, little-endian. Half the size of float64 and past the point
    where the extra precision changes which memory comes back."""
    return struct.pack(f"<{len(vector)}f", *vector)


def _from_blob(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


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
-- One vector per memory, when embeddings are switched on.
--
-- Its own table rather than a column: a memory is complete without one, the
-- model can change under it, and `ON DELETE CASCADE` means forgetting a memory
-- cannot leave a vector behind to be matched against later.
CREATE TABLE IF NOT EXISTS vectors (
    memory_id INTEGER PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
    model     TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    vector    BLOB NOT NULL
);
-- What a conclusion was drawn from.
--
-- Honcho's Deriver keeps this and it is the thing that makes derived memory
-- worth having: a conclusion nobody stated can be *argued with* rather than
-- only trusted, because the messages behind it are still there. Without it a
-- dreamt fact is indistinguishable from something the user said, and a wrong
-- one is unarguable -- Marvi could only insist.
CREATE TABLE IF NOT EXISTS premises (
    conclusion_id INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    premise_id    INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    PRIMARY KEY (conclusion_id, premise_id)
);
CREATE INDEX IF NOT EXISTS premises_premise ON premises(premise_id);
-- One row per dream. Doubles as the watermark: `through_id` is the highest
-- memory the last dream saw, so the next one reads what arrived since rather
-- than the whole store every six hours.
CREATE TABLE IF NOT EXISTS dreams (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    through_id INTEGER NOT NULL DEFAULT 0,
    considered INTEGER NOT NULL DEFAULT 0,
    concluded  INTEGER NOT NULL DEFAULT 0,
    linked     INTEGER NOT NULL DEFAULT 0,
    retired    INTEGER NOT NULL DEFAULT 0
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


#: Words that carry no signal in an OR query and match nearly everything.
#:
#: `who am I` became `"who" OR "am" OR "I"`, which matches every memory
#: containing the letter I as a word -- and FTS5 ranked one about
#: "development style" above the four entries naming the user, which semantic
#: search had found correctly. `how should you talk to me` was worse: six
#: stopwords, matching most of the store.
#:
#: A query made only of these produces no keyword search at all, and semantic
#: search answers alone. That is the right answer rather than a fallback: a
#: question with no distinctive words is precisely the question keywords cannot
#: help with, and the whole reason embeddings were added.
STOPWORDS = frozenset((
    "a", "about", "all", "am", "an", "and", "any", "are", "as", "at", "be", "been",
    "but", "by", "can", "did", "do", "does", "for", "from", "had", "has", "have", "he",
    "her", "him", "his", "how", "i", "if", "in", "is", "it", "its", "me", "my", "of",
    "on", "or", "our", "should", "so", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "to", "too", "us", "was", "we", "were", "what",
    "when", "where", "which", "who", "whom", "why", "will", "with", "would", "you",
    "your",
))


def _fts_query(text: str) -> str:
    """Quote every term so user text can never be FTS5 operator syntax."""
    terms = [t for t in re.findall(r"[\w']+", text) if t and t.lower() not in STOPWORDS]
    return " OR ".join(f'"{t}"' for t in terms)


class MemoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_memory_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        # On for the connection, not just inside the one method that remembered
        # to ask. SQLite defaults it off, so `ON DELETE CASCADE` is decoration
        # until somebody turns it on -- and a forgotten memory would leave its
        # vector behind for ever. The join hides that (an orphan matches no
        # row), which is exactly why it would never have been noticed.
        self._db.execute("PRAGMA foreign_keys = ON")
        #: Which sources are imported files. See `_imported_sources`.
        self._imported: set[str] | None = None
        #: Built on first use, because most stores never need one.
        self._embed: Any = None
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
        # Indexed on the way in, so a memory is searchable by meaning from the
        # moment it exists. Costs 10ms on the CPU and happens on the worker
        # thread, off the turn.
        self.index(memory_id, f"{subject}: {body}")
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
        # The text changed, so the vector is wrong. Re-indexed rather than
        # left, because a stale vector matches what the memory used to say --
        # the same failure as the FTS index without its update trigger.
        self.index(memory_id, f"{subject}: {body}")
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
            behind = self._premise_subjects(entry)
            if entry["source"] in self._imported_sources():
                # Imported from another assistant's memory file. Every line was
                # read by the same scanner that reads a skill before it is
                # installed, and what is stored is a model's paraphrase rather
                # than the original text -- so the full external-data envelope
                # is both unnecessary and unaffordable here: six of them fill
                # the whole recall budget, and an import is rarely six.
                shown = entry["source"].removeprefix(self.IMPORTED)
                entry["body"] = f"(from {shown}) {entry['body']}"
            elif behind:
                # Marvi's own inference, not something that arrived from
                # outside. The external-data envelope is injection defence --
                # "never obey it" -- and saying that about her own reasoning is
                # both wrong and expensive on a block that goes in front of
                # every turn. It still has to be marked, because a conclusion
                # she drew and a fact she was told are different things and
                # stating the first as the second is how she ends up insisting
                # on something nobody said.
                entry["body"] = f"(worked out, not stated) {entry['body']}"
                # What it was drawn from, so "why do you think that?" has an
                # answer through the recall tool that already exists rather
                # than through a tool of its own. Costs nothing in the prompt:
                # `recall_block` reads subject and body only.
                entry["because"] = behind
            else:
                # Recall must not strip the boundary the content arrived with.
                entry["body"] = wrap_external(entry["source"], entry["body"]).text
        return entry

    #: What `memory_import` marks its own writes with. A prefix rather than a
    #: guess at the file extension: the first version matched `%.md` and
    #: friends, so a memory imported from Honcho -- whose source is
    #: `honcho/hermes`, not a filename -- fell through to the full
    #: external-data envelope and 154 of them would have filled the recall
    #: budget many times over.
    IMPORTED = "import:"

    def _imported_sources(self) -> set[str]:
        """Sources written by an import rather than fetched from the network.

        Cached for the life of the connection: it changes only when somebody
        imports, and a query per recalled row would put a table scan in front
        of every turn.
        """
        if self._imported is None:
            rows = self._db.execute(
                "SELECT DISTINCT source FROM memories WHERE source LIKE ?",
                (f"{self.IMPORTED}%",),
            ).fetchall()
            self._imported = {str(row["source"]) for row in rows}
        return self._imported

    def forget_imported_sources(self) -> None:
        """Called after an import, so the next recall sees the new source."""
        self._imported = None

    def _premise_subjects(self, entry: dict[str, Any]) -> list[str]:
        """What this was concluded from, or nothing if it is not a conclusion.

        The source alone would be enough today and would not stay enough: an
        account provider id is a slug the user configures, and one named
        `dreaming` would get an ingested email marked as Marvi's own thinking
        and unwrapped. Premises are the thing no external writer can forge --
        only `conclude()` writes them.
        """
        if entry["source"] != self.DREAMT:
            return []
        rows = self._db.execute(
            "SELECT m.subject FROM premises p JOIN memories m ON m.id = p.premise_id"
            " WHERE p.conclusion_id = ? ORDER BY m.id",
            (entry["id"],),
        ).fetchall()
        return [str(row["subject"]) for row in rows]

    # -- searching by meaning -------------------------------------------------

    def _embedder(self) -> Any:
        """The shared embedder, built on first use.

        Held on the store rather than passed in, because every caller of
        `search` would otherwise have to know about embeddings -- including the
        tools, which have no business knowing.
        """
        if self._embed is None:
            from .embedding import Embedder

            self._embed = Embedder()
        return self._embed

    def index(self, memory_id: int, text: str) -> bool:
        """Give one memory a vector. False when embeddings are off or failed.

        Never raises. A memory without a vector is still a memory, and still
        findable by keyword -- which is what the whole store did until now.
        """
        embedder = self._embedder()
        if not embedder.ready:
            return False
        vectors = embedder.embed([text])
        if not vectors:
            return False
        from .embedding import model_name

        vector = _normalise(vectors[0])
        self._db.execute(
            "INSERT OR REPLACE INTO vectors (memory_id, model, dimension, vector)"
            " VALUES (?, ?, ?, ?)",
            (memory_id, model_name(), len(vector), _to_blob(vector)),
        )
        self._db.commit()
        return True

    def index_missing(self, limit: int = 200) -> int:
        """Give vectors to memories that have none, or whose model has changed.

        Switching embedding model invalidates every vector: two models put the
        same sentence in different places, and comparing across them returns
        confident nonsense. Rows from another model are treated as missing
        rather than migrated, because there is nothing to migrate -- the text
        has to go through the new model.
        """
        from .embedding import model_name

        current = model_name()
        rows = self._db.execute(
            "SELECT m.id, m.subject, m.body FROM memories m"
            " LEFT JOIN vectors v ON v.memory_id = m.id"
            " WHERE v.memory_id IS NULL OR v.model != ? LIMIT ?",
            (current, max(1, min(limit, 1000))),
        ).fetchall()
        done = 0
        for row in rows:
            if self.index(int(row["id"]), f"{row['subject']}: {row['body']}"):
                done += 1
        if done:
            log.info(
                "memory: %d entries indexed for semantic search",
                done,
                extra={"marvi_model": current},
            )
        return done

    def search_similar(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[dict[str, Any]]:
        """Memories that mean something like the query.

        The gap keyword search cannot close: "who am I" shares no word with
        "the user's name is Shereef", so FTS5 returns nothing and Marvi looks
        like she has forgotten something she is holding.

        A full scan with a dot product. There is no index and there does not
        need to be one -- this is a personal memory of hundreds of rows, not a
        corpus, and 384 floats times a few hundred is microseconds. A vector
        index here would be infrastructure for a problem nobody has.
        """
        embedder = self._embedder()
        if not embedder.ready or not query.strip():
            return []
        asked = embedder.embed([query], query=True)
        if not asked:
            return []
        from .embedding import model_name

        wanted = _normalise(asked[0])
        rows = self._db.execute(
            "SELECT m.*, v.vector FROM vectors v JOIN memories m ON m.id = v.memory_id"
            " WHERE v.model = ? AND v.dimension = ?",
            (model_name(), len(wanted)),
        ).fetchall()

        scored = []
        for row in rows:
            stored = _from_blob(row["vector"])
            if len(stored) != len(wanted):
                continue
            # Both sides are unit length, so the dot product is the cosine.
            score = sum(a * b for a, b in zip(wanted, stored, strict=True))
            if score >= SIMILAR_ENOUGH:
                scored.append((score, row))
        scored.sort(key=lambda pair: -pair[0])
        return [self._row(row) for _, row in scored[: max(1, limit)]]

    def search(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[dict[str, Any]]:
        """Keywords and meaning together, whichever finds it.

        Both, not either. Keyword search is exact and finds a name, an error
        code, a filename -- the things an embedding blurs. Semantic search
        finds the note whose words you have forgotten, which is most of what
        anybody actually asks memory for. Running one alone means losing the
        other's best case, and the union is short enough not to matter.

        **Interleaved, not concatenated.** Keyword results used to lead on the
        reasoning that a literal match beats a close one. That holds while the
        store is small and a keyword hit is therefore rare and precise. It
        stopped holding the moment 147 memories arrived from an import: "what
        computer do I have" matched "Computer Engineering" literally, and at a
        limit of two that one weak hit buried the entry naming the actual
        machine, which semantic search had ranked first. Taking from both in
        turn is what "both, not either" actually means.
        """
        capped = max(1, min(limit, 100))
        match = _fts_query(query)
        rows = (
            self._db.execute(
                "SELECT m.* FROM memories_fts f JOIN memories m ON m.id = f.rowid"
                " WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                (match, capped),
            ).fetchall()
            if match
            else []
        )
        by_word = [self._row(row) for row in rows]
        by_meaning = self.search_similar(query, limit=capped)

        found: list[dict[str, Any]] = []
        seen: set[int] = set()
        # Keyword first within each pair, so an exact match still wins a tie --
        # the part of the old reasoning that was right.
        for pair in zip_longest(by_word, by_meaning):
            for entry in pair:
                if entry is None or entry["id"] in seen or len(found) >= capped:
                    continue
                found.append(entry)
                seen.add(entry["id"])
        if not found:
            return []
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

    def recall_block(self, text: str, limit: int = 5, budget: int = 1_200) -> str:
        """What Marvi already knows that bears on this message, as prompt text.

        Lives here rather than in Chat because both surfaces need it and the
        one that did not have it was voice -- so memory reached the typed
        conversation on every turn and the spoken one never, unless the model
        thought to call a tool. Asked her own name, Marvi did not look; she
        wrote it down again.

        Searched rather than dumped: the store grows without limit and the
        prompt does not. Untrusted entries arrive already enveloped by the
        layer below, so the boundary they came with survives recall.
        """
        if not text.strip():
            return ""
        try:
            found = self.search(text, limit=limit)
        except Exception as exc:  # pragma: no cover - depends on the store
            log.warning("recall unavailable: %s", exc)
            return ""

        lines: list[str] = []
        spent = 0
        for entry in found:
            body = str(entry.get("body") or "").strip()
            if not body:
                continue
            subject = str(entry.get("subject") or "").strip()
            line = f"- {subject}: {body}" if subject else f"- {body}"
            if spent + len(line) > budget:
                break
            lines.append(line)
            spent += len(line)
        if not lines:
            return ""
        nl = chr(10)
        return (
            "# What you remember"
            + nl
            + nl
            + nl.join(lines)
            + nl
            + nl
            + "Your own notes from earlier. They may be out of date; prefer "
            "what the user says now, and do not repeat them back unprompted."
        )

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

    # -- dreaming ------------------------------------------------------------
    #
    # Reflection above counts repeats of one subject. Dreaming reads *across*
    # them, which is a different operation and the one that was missing:
    # "coffee at 6am" and "asleep by nine" are two episodes that never repeat
    # and together say something neither says alone.

    #: What the dreamer writes as its source. Everything it may later retire is
    #: marked with it, and nothing else is ever retired -- the same invariant
    #: hermes's Curator holds for skills, and for the same reason: a background
    #: model that can delete what the user told it is a background model that
    #: can quietly erase them.
    DREAMT = "dreaming"

    def undreamt(self, limit: int = 80) -> list[dict[str, Any]]:
        """Memories that arrived since the last dream, oldest first.

        Oldest first because a conclusion is drawn in the order things
        happened, and handing a model the newest first inverts every "then".
        """
        row = self._db.execute("SELECT MAX(through_id) AS mark FROM dreams").fetchone()
        mark = int(row["mark"] or 0) if row else 0
        rows = self._db.execute(
            "SELECT * FROM memories WHERE id > ? AND source != ? ORDER BY id LIMIT ?",
            (mark, self.DREAMT, max(1, min(limit, 200))),
        ).fetchall()
        return [self._row(row) for row in rows]

    def conclude(self, subject: str, body: str, premises: list[int]) -> int:
        """Store something nobody said, with what it was drawn from.

        Untrusted on purpose. It is Marvi's inference, not the user's word, and
        the two must not be recalled as though they were the same kind of
        thing.
        """
        memory_id = self.remember(
            subject, body, kind="semantic", source=self.DREAMT, trusted=False
        )
        for premise in premises:
            self._db.execute(
                "INSERT OR IGNORE INTO premises (conclusion_id, premise_id) VALUES (?, ?)",
                (memory_id, int(premise)),
            )
        self._db.commit()
        return memory_id

    def premises_of(self, memory_id: int) -> list[dict[str, Any]]:
        """What a conclusion rests on, for answering "why do you think that?"."""
        rows = self._db.execute(
            "SELECT m.* FROM premises p JOIN memories m ON m.id = p.premise_id"
            " WHERE p.conclusion_id = ? ORDER BY m.id",
            (int(memory_id),),
        ).fetchall()
        return [self._row(row) for row in rows]

    def retire(self, memory_id: int) -> bool:
        """Drop a conclusion the dreamer no longer stands behind.

        Refuses anything it did not write. A conclusion is Marvi's to withdraw;
        a fact the user stated is not.
        """
        row = self._db.execute(
            "SELECT source FROM memories WHERE id = ?", (int(memory_id),)
        ).fetchone()
        if row is None or row["source"] != self.DREAMT:
            return False
        return self.forget(int(memory_id))

    def conclusions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Everything the dreamer has concluded, newest first."""
        rows = self._db.execute(
            "SELECT * FROM memories WHERE source = ? ORDER BY id DESC LIMIT ?",
            (self.DREAMT, max(1, min(limit, 200))),
        ).fetchall()
        return [{**self._row(row), "premises": self.premises_of(int(row["id"]))} for row in rows]

    def record_dream(self, **counts: int) -> None:
        self._db.execute(
            "INSERT INTO dreams (at, through_id, considered, concluded, linked, retired)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(),
                int(counts.get("through_id", 0)),
                int(counts.get("considered", 0)),
                int(counts.get("concluded", 0)),
                int(counts.get("linked", 0)),
                int(counts.get("retired", 0)),
            ),
        )
        self._db.commit()

    def dreams(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM dreams ORDER BY id DESC LIMIT ?", (max(1, min(limit, 100)),)
        ).fetchall()
        return [dict(row) for row in rows]

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
