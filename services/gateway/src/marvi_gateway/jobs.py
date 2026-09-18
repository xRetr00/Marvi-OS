"""The board: every job Marvi is doing, has done, or is stuck on.

Sub-agent jobs lived in a dictionary in `subagents.py` and coder jobs in
another one in `delegate.py`. Both died with the process, which is the wrong
lifetime for the thing they describe: "Harvi is fixing the failing test" is
still true after a restart, and the only honest thing a board could say about
it was nothing at all.

So a card is a row. It survives a restart, it carries its own history -- every
attempt, every comment, every transition -- and it is the one place the window,
the model and Telegram all read from.

## The states, and why `blocked` is one of them

    todo -> running -> (awaiting_approval | blocked) -> done | failed | cancelled

`awaiting_approval` and `blocked` are separate because they need different
things from the person: one wants a tap, the other wants an answer. Collapsing
them into "running" is what made a stalled job indistinguishable from a slow
one, which is the failure the Codex and Claude Code cards are known for and the
reason every state here is the Gateway's rather than the window's.

## Restart

A card left `running` by a process that is no longer alive is not running. On
startup those become `failed` with `exit_reason=restart` -- said plainly rather
than left spinning forever. Whatever the job wrote to disk is untouched; only
the card's belief about itself is corrected.

## Revisions

Every change bumps a revision, and `GET /jobs?after=<revision>` long-polls for
the next one. The window does not poll on a timer: a board that repaints every
two seconds is a board nobody can read while it changes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .logs import get_logger

log = get_logger("gateway")

STATES = ("todo", "running", "awaiting_approval", "blocked", "done", "failed", "cancelled")

#: The states a card can still change from. Used to decide what a restart
#: has to correct, and what a comment can still reach.
LIVE = ("todo", "running", "awaiting_approval", "blocked")

#: Why a card is blocked. Each one asks the person for something different.
BLOCKED_REASONS = ("needs_input", "dependency", "stalled")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL DEFAULT '',
    assignee   TEXT NOT NULL DEFAULT 'worker',
    mode       TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'todo',
    reason     TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT 'marvi',
    thread_id  TEXT NOT NULL DEFAULT '',
    job_id     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revision   INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS tasks_status ON tasks(status, updated_at);
CREATE TABLE IF NOT EXISTS task_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    exit_reason TEXT NOT NULL DEFAULT '',
    summary     TEXT NOT NULL DEFAULT '',
    tokens      INTEGER NOT NULL DEFAULT 0,
    provider    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS task_runs_task ON task_runs(task_id, id);
CREATE TABLE IF NOT EXISTS task_comments (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    author  TEXT NOT NULL,
    body    TEXT NOT NULL,
    at      TEXT NOT NULL,
    steered INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS task_comments_task ON task_comments(task_id, id);
CREATE TABLE IF NOT EXISTS task_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    kind    TEXT NOT NULL,
    detail  TEXT NOT NULL DEFAULT '',
    at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS task_events_task ON task_events(task_id, id);
"""


def default_path() -> Path:
    from .paths import root

    return root() / "jobs.sqlite3"


class JobsStore:
    """Cards, their attempts, their comments and their history."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()
        self._lock = threading.Lock()
        #: Bumped by every change; the long poll waits on it.
        self._revision = int(
            self._db.execute("SELECT COALESCE(MAX(revision), 0) AS r FROM tasks").fetchone()["r"]
        )
        self._changed = threading.Condition()

    # -- the board ------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")

    @property
    def revision(self) -> int:
        return self._revision

    def _bump(self) -> int:
        with self._changed:
            self._revision += 1
            self._changed.notify_all()
            return self._revision

    def wait(self, after: int, timeout: float = 25.0) -> int:
        """Block until the board changes past `after`, or the timeout passes.

        The long poll the window holds open. A board that repaints on a timer
        is one nobody can read while it changes, and one that never repaints is
        a board nobody trusts.
        """
        with self._changed:
            if self._revision > after:
                return self._revision
            self._changed.wait(timeout=timeout)
            return self._revision

    def add(
        self,
        title: str,
        body: str = "",
        assignee: str = "worker",
        mode: str = "",
        created_by: str = "marvi",
        thread_id: str = "",
        job_id: str = "",
        status: str = "todo",
    ) -> dict[str, Any]:
        identifier = uuid4().hex[:12]
        now = self._now()
        with self._lock:
            self._db.execute(
                "INSERT INTO tasks (id, title, body, assignee, mode, status, created_by,"
                " thread_id, job_id, created_at, updated_at, revision)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    " ".join((title or "").split())[:200] or "Untitled job",
                    body,
                    assignee,
                    mode,
                    status if status in STATES else "todo",
                    created_by,
                    thread_id,
                    job_id,
                    now,
                    now,
                    self._bump(),
                ),
            )
            self._event(identifier, "created", f"{created_by} -> {assignee}")
            self._db.commit()
        return self.get(identifier)

    def _event(self, task_id: str, kind: str, detail: str = "") -> None:
        self._db.execute(
            "INSERT INTO task_events (task_id, kind, detail, at) VALUES (?, ?, ?, ?)",
            (task_id, kind, detail[:500], self._now()),
        )

    def get(self, task_id: str) -> dict[str, Any]:
        row = self._db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"no job called {task_id}")
        card = dict(row)
        card["runs"] = [
            dict(one)
            for one in self._db.execute(
                "SELECT * FROM task_runs WHERE task_id = ? ORDER BY id", (task_id,)
            )
        ]
        card["comments"] = [
            dict(one)
            for one in self._db.execute(
                "SELECT * FROM task_comments WHERE task_id = ? ORDER BY id", (task_id,)
            )
        ]
        card["events"] = [
            dict(one)
            for one in self._db.execute(
                "SELECT * FROM task_events WHERE task_id = ? ORDER BY id DESC LIMIT 40", (task_id,)
            )
        ]
        return card

    def board(self, limit: int = 200) -> dict[str, Any]:
        """Every card, grouped by state, newest first inside each column."""
        rows = [
            dict(one)
            for one in self._db.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?", (max(1, limit),)
            )
        ]
        columns: dict[str, list[dict[str, Any]]] = {state: [] for state in STATES}
        for row in rows:
            columns.setdefault(row["status"], []).append(row)
        return {"revision": self._revision, "columns": columns, "total": len(rows)}

    # -- what happens to a card ----------------------------------------------

    def set_status(
        self, task_id: str, status: str, reason: str = "", detail: str = ""
    ) -> dict[str, Any]:
        if status not in STATES:
            raise ValueError(f"unknown status {status!r}")
        with self._lock:
            self.get(task_id)  # raises for an unknown card
            self._db.execute(
                "UPDATE tasks SET status = ?, reason = ?, updated_at = ?, revision = ? WHERE id = ?",
                (status, reason, self._now(), self._bump(), task_id),
            )
            self._event(task_id, status, detail or reason)
            self._db.commit()
        return self.get(task_id)

    def edit(self, task_id: str, title: str | None = None, body: str | None = None) -> dict[str, Any]:
        with self._lock:
            self.get(task_id)
            if title is not None:
                self._db.execute(
                    "UPDATE tasks SET title = ?, updated_at = ?, revision = ? WHERE id = ?",
                    (" ".join(title.split())[:200] or "Untitled job", self._now(), self._bump(), task_id),
                )
            if body is not None:
                self._db.execute(
                    "UPDATE tasks SET body = ?, updated_at = ?, revision = ? WHERE id = ?",
                    (body, self._now(), self._bump(), task_id),
                )
            self._db.commit()
        return self.get(task_id)

    def start_run(self, task_id: str) -> int:
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO task_runs (task_id, started_at) VALUES (?, ?)",
                (task_id, self._now()),
            )
            self._db.execute(
                "UPDATE tasks SET status = 'running', reason = '', updated_at = ?, revision = ?"
                " WHERE id = ?",
                (self._now(), self._bump(), task_id),
            )
            self._event(task_id, "running", "attempt started")
            self._db.commit()
            return int(cursor.lastrowid or 0)

    def finish_run(
        self,
        run_id: int,
        exit_reason: str,
        summary: str = "",
        tokens: int = 0,
        provider: str = "",
        status: str = "",
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT task_id FROM task_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            task_id = str(row["task_id"])
            self._db.execute(
                "UPDATE task_runs SET finished_at = ?, exit_reason = ?, summary = ?, tokens = ?,"
                " provider = ? WHERE id = ?",
                (self._now(), exit_reason, summary[:4000], int(tokens), provider, run_id),
            )
            landed = status or ("done" if exit_reason == "completed" else "failed")
            self._db.execute(
                "UPDATE tasks SET status = ?, updated_at = ?, revision = ? WHERE id = ?",
                (landed, self._now(), self._bump(), task_id),
            )
            self._event(task_id, landed, exit_reason)
            self._db.commit()
        return self.get(task_id)

    def comment(self, task_id: str, body: str, author: str = "owner") -> dict[str, Any]:
        """Append a comment. On a live card from the owner it is also a steer.

        The flag is what `subagents` reads to interrupt a running job with the
        owner's words, which is the difference between a comment and a note.
        """
        card = self.get(task_id)
        steering = author == "owner" and card["status"] in LIVE
        with self._lock:
            self._db.execute(
                "INSERT INTO task_comments (task_id, author, body, at, steered)"
                " VALUES (?, ?, ?, ?, ?)",
                (task_id, author, body[:4000], self._now(), 1 if steering else 0),
            )
            self._db.execute(
                "UPDATE tasks SET updated_at = ?, revision = ? WHERE id = ?",
                (self._now(), self._bump(), task_id),
            )
            self._event(task_id, "comment", f"{author}: {body[:120]}")
            self._db.commit()
        return {**self.get(task_id), "steered": steering}

    def unsent_steers(self, task_id: str) -> list[str]:
        """Owner comments on a live card, oldest first, marked as sent."""
        rows = self._db.execute(
            "SELECT id, body FROM task_comments WHERE task_id = ? AND steered = 1 ORDER BY id",
            (task_id,),
        ).fetchall()
        if not rows:
            return []
        with self._lock:
            self._db.execute(
                "UPDATE task_comments SET steered = 2 WHERE task_id = ? AND steered = 1", (task_id,)
            )
            self._db.commit()
        return [str(row["body"]) for row in rows]

    def remove(self, task_id: str) -> bool:
        with self._lock:
            removed = self._db.execute("DELETE FROM tasks WHERE id = ?", (task_id,)).rowcount
            self._db.commit()
            if removed:
                self._bump()
        return bool(removed)

    # -- restart --------------------------------------------------------------

    def recover(self) -> int:
        """Correct cards a dead process left running. Returns how many.

        Called once at startup. A card that says "running" when nothing is
        running is the single most misleading thing a board can show, and it is
        exactly what a crash leaves behind.
        """
        rows = self._db.execute(
            "SELECT id FROM tasks WHERE status IN ('running', 'awaiting_approval')"
        ).fetchall()
        for row in rows:
            self._db.execute(
                "UPDATE task_runs SET finished_at = ?, exit_reason = 'restart'"
                " WHERE task_id = ? AND finished_at = ''",
                (self._now(), row["id"]),
            )
            self._db.execute(
                "UPDATE tasks SET status = 'failed', reason = 'restart', updated_at = ?,"
                " revision = ? WHERE id = ?",
                (self._now(), self._bump(), row["id"]),
            )
            self._event(row["id"], "failed", "the Gateway restarted while this was running")
        self._db.commit()
        if rows:
            log.info("%d job(s) were interrupted by a restart", len(rows))
        return len(rows)

    def close(self) -> None:
        self._db.close()


def register_job_tools(registry: Any, store: JobsStore) -> None:
    from .tools import ToolSpec

    def jobs_board(status: str = "") -> dict[str, Any]:
        board = store.board()
        if status:
            return {"cards": board["columns"].get(status, [])}
        return {
            state: [
                {"id": card["id"], "title": card["title"], "assignee": card["assignee"],
                 "reason": card["reason"]}
                for card in cards
            ]
            for state, cards in board["columns"].items()
            if cards
        }

    def job_add(title: str, body: str = "", assignee: str = "owner") -> dict[str, Any]:
        card = store.add(title, body, assignee=assignee, created_by="marvi")
        return {"id": card["id"], "title": card["title"], "status": card["status"]}

    def job_update(job: str, status: str = "", note: str = "") -> dict[str, Any]:
        try:
            if note:
                store.comment(job, note, author="marvi")
            card = store.set_status(job, status) if status else store.get(job)
        except (KeyError, ValueError) as exc:
            return {"error": str(exc)}
        return {"id": card["id"], "status": card["status"], "title": card["title"]}

    registry.register(ToolSpec(
        name="jobs_board",
        description="Every job on the board, by state.",
        arguments={},
        optional={"status": str},
        sensitive=False,
        handler=jobs_board,
        describes={"status": f"Only one column: {', '.join(STATES)}. Leave out for all of them."},
    ))
    registry.register(ToolSpec(
        name="job_add",
        description="Put a job on the board.",
        arguments={"title": str},
        optional={"body": str, "assignee": str},
        sensitive=False,
        handler=job_add,
        describes={
            "title": "What needs doing, in a few words.",
            "body": "Anything else worth keeping with it.",
            "assignee": "Who it is for: owner, harvi, jarvi, talos, or worker.",
        },
    ))
    registry.register(ToolSpec(
        name="job_update",
        description="Move a job on the board, or add a note to it.",
        arguments={"job": str},
        optional={"status": str, "note": str},
        sensitive=False,
        handler=job_update,
        describes={
            "job": "The job id from jobs_board.",
            "status": f"One of {', '.join(STATES)}.",
            "note": "A line to keep on the card.",
        },
    ))
