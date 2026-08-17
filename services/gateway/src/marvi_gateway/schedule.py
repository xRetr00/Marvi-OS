"""User-scheduled reminders, on top of the initiative scheduler.

The APScheduler that drives Marvi's own ticks was already here. What was missing
is the half the user controls: "wake me at seven", "remind me to call mum on
Sunday", "check my email every hour".

## Three decisions worth stating

**Stored in Marvi's own database, not APScheduler's job store.** A reminder is
the user's data. It has to survive a restart, an update and a crash, and it has
to be readable and deletable by a person looking at their own machine. An opaque
pickled job store fails all of that.

**Firing writes a journal event; it does not speak.** A reminder becomes
`source="schedule"` in the journal and the mind decides what to do with it,
through the same proactivity policy as everything else. So a reminder cannot
talk over a live conversation and cannot escape the audit trail — and it needed
no new path to the speaker.

**Bypassing quiet hours is per-schedule and opt-in.** Quiet hours downgrade
Marvi's own initiative from speech to a glance, which is right. Applying that to
an alarm the user set for 07:00 would make it useless — an alarm that appears
silently on a screen is not an alarm.

But the first version of this exempted *every* schedule, and that was too broad:
"check my email hourly" firing out loud at 3am is the thing quiet hours exists to
prevent, and the user did not ask for that by asking for the check. So `insist`
is a flag on the schedule. Off by default; on for the alarm, where the user chose
the time and meant it. It also overrides sleep mode, because "wake me at seven"
is precisely a request to be woken.

`insist` is the only thing that crosses those two lines, and nothing else does:
a schedule still cannot talk over a live conversation, still obeys the cooldown,
and is still capped by its ceiling.

## What a reminder is not

It is not a general cron that runs commands. `action` names something Marvi
already knows how to do, from a fixed set; a schedule cannot introduce a new
capability, only re-time an existing one. Arbitrary scheduled shell commands
would be the most convenient possible way to turn a reminder into a persistence
mechanism.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import paths
from .logs import get_logger

log = get_logger("schedule")

#: What a schedule is allowed to trigger. A schedule re-times something Marvi can
#: already do; it never introduces a new capability. Anything not here is
#: refused, which is what stops a reminder becoming a way to run commands.
ACTIONS = {
    "remind": "Say something back to you at a chosen time",
    "check_accounts": "Pull new account items and journal them",
    "reflect": "Look back over recent events and write down what matters",
}

#: A schedule that fires more often than this is a stream, not a reminder.
MINIMUM_INTERVAL_MINUTES = 5

#: Belt and braces against a runaway list; a person has tens of reminders, not
#: thousands, and a bug that adds one per tick should hit a wall.
MAX_SCHEDULES = 200


class ScheduleError(Exception):
    """A schedule Marvi will not accept, with the reason."""


@dataclass(frozen=True)
class Schedule:
    id: int
    name: str
    action: str
    #: Either `cron` (a five-field expression) or `interval` (minutes).
    kind: str
    expression: str
    message: str
    enabled: bool
    created_at: str
    #: Speak even during quiet hours and while the room is in sleep mode. The
    #: user asked for this time and meant it; an alarm that stays silent is not
    #: an alarm. Off by default — an hourly mail check has not earned it.
    insist: bool = False
    last_run: str | None = None
    last_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "action": self.action,
            "kind": self.kind,
            "expression": self.expression,
            "message": self.message,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "insist": self.insist,
            "last_run": self.last_run,
            "last_error": self.last_error,
        }


def _validate(action: str, kind: str, expression: str) -> None:
    if action not in ACTIONS:
        raise ScheduleError(
            f"unknown action {action!r}; Marvi can schedule: {', '.join(sorted(ACTIONS))}"
        )
    if kind == "interval":
        try:
            minutes = int(expression)
        except (TypeError, ValueError) as exc:
            raise ScheduleError("an interval is a whole number of minutes") from exc
        if minutes < MINIMUM_INTERVAL_MINUTES:
            raise ScheduleError(
                f"the shortest interval is {MINIMUM_INTERVAL_MINUTES} minutes; "
                "anything faster is a stream, not a reminder"
            )
        return
    if kind == "cron":
        fields = expression.split()
        if len(fields) != 5:
            raise ScheduleError(
                "a cron expression has five fields: minute hour day month weekday"
            )
        # Built with the thing that will actually run it. Counting fields is not
        # validation: "99 99 * * *" has five and is not a time, and accepting it
        # meant the reminder was stored, listed as enabled, and silently never
        # fired because the scheduler refused it at start.
        try:
            from apscheduler.triggers.cron import CronTrigger

            CronTrigger.from_crontab(expression, timezone="UTC")
        except Exception as exc:
            raise ScheduleError(f"{expression!r} is not a schedule: {exc}") from exc
        return
    raise ScheduleError(f"unknown schedule kind {kind!r}; use 'cron' or 'interval'")


class ScheduleStore:
    """Reminders on disk. Small, readable, and the user's to delete."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.root() / "schedules.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                action TEXT NOT NULL,
                kind TEXT NOT NULL,
                expression TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                insist INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_run TEXT,
                last_error TEXT
            )
            """
        )
        # Added after the first release of this table. `ALTER TABLE` rather
        # than a rebuild, so nobody's reminders are dropped by an upgrade.
        columns = {
            row["name"] for row in self._db.execute("PRAGMA table_info(schedules)")
        }
        if "insist" not in columns:
            self._db.execute(
                "ALTER TABLE schedules ADD COLUMN insist INTEGER NOT NULL DEFAULT 0"
            )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _row(row: sqlite3.Row) -> Schedule:
        return Schedule(
            id=int(row["id"]),
            name=str(row["name"]),
            action=str(row["action"]),
            kind=str(row["kind"]),
            expression=str(row["expression"]),
            message=str(row["message"] or ""),
            enabled=bool(row["enabled"]),
            created_at=str(row["created_at"]),
            insist=bool(row["insist"]),
            last_run=row["last_run"],
            last_error=row["last_error"],
        )

    def add(
        self,
        name: str,
        action: str,
        kind: str,
        expression: str,
        message: str = "",
        insist: bool = False,
        now: datetime | None = None,
    ) -> Schedule:
        label = (name or "").strip()
        if not label:
            raise ScheduleError("a schedule needs a name, so it can be found and cancelled")
        _validate(action, kind, expression)
        if self.count() >= MAX_SCHEDULES:
            raise ScheduleError(f"there are already {MAX_SCHEDULES} schedules; remove some first")

        moment = (now or datetime.now(UTC)).isoformat()
        cursor = self._db.execute(
            "INSERT INTO schedules"
            " (name, action, kind, expression, message, insist, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                label,
                action,
                kind,
                str(expression),
                message.strip(),
                1 if insist else 0,
                moment,
            ),
        )
        self._db.commit()
        log.info(
            "schedule added",
            extra={"marvi_schedule": label, "marvi_action": action, "marvi_when": expression},
        )
        return self.get(int(cursor.lastrowid or 0))

    def get(self, schedule_id: int) -> Schedule:
        row = self._db.execute(
            "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
        if row is None:
            raise ScheduleError(f"no schedule with id {schedule_id}")
        return self._row(row)

    def list(self, include_disabled: bool = True) -> list[Schedule]:
        query = "SELECT * FROM schedules"
        if not include_disabled:
            query += " WHERE enabled = 1"
        query += " ORDER BY id"
        return [self._row(row) for row in self._db.execute(query)]

    def count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM schedules").fetchone()[0])

    def set_enabled(self, schedule_id: int, enabled: bool) -> Schedule:
        self.get(schedule_id)
        self._db.execute(
            "UPDATE schedules SET enabled = ? WHERE id = ?", (1 if enabled else 0, schedule_id)
        )
        self._db.commit()
        return self.get(schedule_id)

    def remove(self, schedule_id: int) -> bool:
        cursor = self._db.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        self._db.commit()
        if cursor.rowcount:
            log.info("schedule removed", extra={"marvi_schedule": str(schedule_id)})
        return bool(cursor.rowcount)

    def record_run(
        self, schedule_id: int, error: str | None = None, now: datetime | None = None
    ) -> None:
        self._db.execute(
            "UPDATE schedules SET last_run = ?, last_error = ? WHERE id = ?",
            ((now or datetime.now(UTC)).isoformat(), (error or "")[:200] or None, schedule_id),
        )
        self._db.commit()


class Scheduler:
    """Runs the user's schedules, and reports what happened.

    Deliberately not APScheduler's persistence: the store above is the record,
    and this rebuilds the jobs from it on every start. That means one place to
    look when a reminder does not fire, and no pickled state to go stale across
    an update.
    """

    def __init__(self, store: ScheduleStore, journal: Any = None, initiative: Any = None) -> None:
        self.store = store
        self.journal = journal
        self.initiative = initiative
        self._scheduler: Any = None

    def fire(self, schedule_id: int) -> dict[str, Any]:
        """Run one schedule. Never raises: a bad schedule must not stop the rest."""
        try:
            schedule = self.store.get(schedule_id)
        except ScheduleError as exc:
            return {"ok": False, "detail": str(exc)}
        if not schedule.enabled:
            return {"ok": True, "detail": "disabled", "skipped": True}

        try:
            if schedule.action == "remind":
                if self.journal is None:
                    raise ScheduleError("no journal to record the reminder in")
                # Written, not spoken. The mind decides how loud it may be, and
                # `source="schedule"` is what tells the policy the user asked
                # for this at a time they chose.
                self.journal.append(
                    "schedule",
                    # The kind is what the policy reads, so the opt-in has to be
                    # visible there rather than hidden in the payload.
                    "insistent_reminder" if schedule.insist else "reminder",
                    schedule.message or schedule.name,
                    {
                        "schedule_id": schedule.id,
                        "name": schedule.name,
                        "insist": schedule.insist,
                    },
                    trusted=True,
                )
            elif schedule.action == "check_accounts":
                if self.initiative is None:
                    raise ScheduleError("account ingestion is not available")
                self.initiative.run_ingest()
            elif schedule.action == "reflect":
                if self.initiative is None:
                    raise ScheduleError("reflection is not available")
                self.initiative.run_reflect()
            else:
                raise ScheduleError(f"unknown action {schedule.action}")
        except Exception as exc:
            self.store.record_run(schedule_id, error=str(exc))
            log.warning("schedule %s failed: %s", schedule.name, exc)
            return {"ok": False, "detail": str(exc)[:200]}

        self.store.record_run(schedule_id)
        log.info("schedule fired", extra={"marvi_schedule": schedule.name})
        return {"ok": True, "detail": "fired"}

    def start(self) -> int:
        """Build jobs from the store. Returns how many are running."""
        if self._scheduler is not None:
            return 0
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
        running = 0
        for schedule in self.store.list(include_disabled=False):
            try:
                if schedule.kind == "cron":
                    trigger = CronTrigger.from_crontab(schedule.expression, timezone="UTC")
                else:
                    trigger = IntervalTrigger(minutes=int(schedule.expression))
            except Exception as exc:
                # A schedule that cannot be built is recorded against itself
                # rather than taking the scheduler down with it.
                self.store.record_run(schedule.id, error=f"invalid schedule: {exc}")
                continue
            scheduler.add_job(
                self.fire,
                trigger,
                args=[schedule.id],
                id=f"schedule-{schedule.id}",
                max_instances=1,
                # A machine that was asleep should not fire six hours of missed
                # reminders at once when it wakes.
                coalesce=True,
                misfire_grace_time=300,
            )
            running += 1
        scheduler.start()
        self._scheduler = scheduler
        log.info("scheduler started", extra={"marvi_jobs": str(running)})
        return running

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    def reload(self) -> int:
        """Rebuild after a change. Adding a reminder should not need a restart."""
        self.stop()
        return self.start()

    def status(self) -> dict[str, Any]:
        return {
            "running": self._scheduler is not None,
            "schedules": [s.as_dict() for s in self.store.list()],
            "actions": ACTIONS,
        }


def register_schedule_tools(registry: Any, scheduler: Scheduler) -> None:
    """Let voice and chat set, list and cancel reminders."""
    from .tools import ToolSpec

    def schedule_add(
        name: str,
        when: str,
        message: str = "",
        action: str = "remind",
        insist: bool = False,
    ) -> dict:
        """`when` is either "HH:MM" or a cron expression or a number of minutes.

        `insist` is the alarm case: speak even during quiet hours and even while
        the room is asleep. It is off unless asked for, because "check my mail
        hourly" firing out loud at 3am is what quiet hours is for.
        """
        kind, expression = "cron", when.strip()
        if expression.isdigit():
            kind, expression = "interval", expression
        elif ":" in expression and len(expression.split(":")) == 2:
            # "07:30" is what a person says; cron wants "30 7 * * *".
            hour, _, minute = expression.partition(":")
            try:
                expression = f"{int(minute)} {int(hour)} * * *"
            except ValueError as exc:
                raise ScheduleError(f"{when!r} is not a time Marvi understands") from exc
        return scheduler.store.add(
            name, action, kind, expression, message, insist=bool(insist)
        ).as_dict()

    def schedule_list() -> dict:
        return {"schedules": [s.as_dict() for s in scheduler.store.list()]}

    def schedule_remove(id: int) -> dict:  # noqa: A002 - the argument the model sends
        removed = scheduler.store.remove(int(id))
        return {"removed": removed}

    registry.register(
        ToolSpec(
            name="schedule_list",
            description="List the reminders and scheduled checks",
            arguments={},
            sensitive=False,
            handler=schedule_list,
        )
    )
    registry.register(
        ToolSpec(
            name="schedule_add",
            description="Set a reminder or a scheduled check",
            arguments={"name": str, "when": str},
            optional={"message": str, "action": str, "insist": bool},
            # Confirmed: a schedule is a standing instruction that will act
            # again later, which is exactly the kind of thing worth agreeing to
            # once rather than discovering at seven in the morning.
            sensitive=True,
            handler=schedule_add,
        )
    )
    registry.register(
        ToolSpec(
            name="schedule_remove",
            description="Cancel a reminder",
            arguments={"id": int},
            sensitive=True,
            handler=schedule_remove,
        )
    )
