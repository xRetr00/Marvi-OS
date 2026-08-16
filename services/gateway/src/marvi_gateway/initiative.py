"""Scheduled initiative.

APScheduler 3.x drives four bounded ticks. None of them touch the voice path:
they run on the scheduler's own threads and talk to SQLite and HTTP clients
that the foreground never waits on.

    ingest      pull new account items into the journal
    mind        decide what, if anything, to do about pending events
    reflect     promote repeated episodes into durable facts
    consolidate the sleep pass: forget stale, never-recalled episodes

Every job is wrapped so a failure is recorded and skipped rather than killing
the scheduler — an assistant whose background mind dies silently is worse than
one that misses a tick.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

INGEST_MINUTES = 10
MIND_MINUTES = 2
REFLECT_HOURS = 6
CONSOLIDATE_HOURS = 24


class Initiative:
    """Owns the background schedule and the pause switch."""

    def __init__(
        self,
        mind: Any,
        journal: Any,
        ingest: Any = None,
        memory: Any = None,
        room_state: Any = None,
        faces: Any = None,
    ) -> None:
        self.mind = mind
        self.journal = journal
        self.ingest = ingest
        self.memory = memory
        self.room_state = room_state
        self.faces = faces
        self._was_home = True
        self._scheduler: Any = None
        self.last_runs: dict[str, str] = {}
        self.last_errors: dict[str, str] = {}

    # -- state ---------------------------------------------------------------

    @property
    def paused(self) -> bool:
        return self.mind.settings.paused

    def set_paused(self, paused: bool) -> bool:
        """Pausing stops decisions, not observation.

        Events keep landing in the journal while paused, so turning initiative
        back on shows what was missed instead of a silent gap.
        """
        self.mind.settings.paused = paused
        return self.mind.settings.paused

    def status(self) -> dict[str, Any]:
        return {
            "paused": self.paused,
            "running": bool(self._scheduler and self._scheduler.running),
            "pending_events": self.journal.count_pending(),
            "last_runs": dict(self.last_runs),
            "last_errors": dict(self.last_errors),
            "settings": {
                "quiet_start": self.mind.settings.quiet_start,
                "quiet_end": self.mind.settings.quiet_end,
                "cooldown_seconds": self.mind.settings.cooldown_seconds,
                "daily_token_budget": self.mind.settings.daily_token_budget,
            },
        }

    # -- jobs ----------------------------------------------------------------

    def _guard(self, name: str, work: Any) -> Any:
        def run() -> None:
            try:
                work()
                self.last_runs[name] = datetime.now(UTC).isoformat()
                self.last_errors.pop(name, None)
            except Exception as exc:
                self.last_errors[name] = str(exc)[:200]
                logger.warning("initiative job %s failed: %s", name, exc)

        return run

    def run_ingest(self) -> dict[str, Any]:
        """Pull account items and journal them. Ingestion runs even when paused
        so nothing is lost; only decisions stop."""
        if self.ingest is None:
            return {"ingested": []}
        result = self.ingest.poll()
        for subject in result.get("ingested", []):
            kind = "calendar" if subject.startswith("Event:") else "email"
            self.journal.append("accounts", kind, subject, {"id": subject}, trusted=False)
        return result

    def run_mind(self) -> dict[str, Any]:
        present, conversation = True, False
        if self.room_state is not None:
            try:
                snapshot = self.room_state()
                present = bool(snapshot.get("present", True))
                conversation = bool(snapshot.get("conversation_active", False))
            except Exception:
                pass
        return self.mind.tick(conversation_active=conversation, present=present)

    def run_homecoming(self, present: bool | None = None) -> dict[str, Any]:
        """Report visitors on the away -> home edge.

        Telling someone about a stranger while they are still out is useless
        and slightly alarming, so sightings queue until they are back.
        """
        if self.faces is None:
            return {"reported": []}
        if present is None:
            present = self._presence()
        arrived = present and not self._was_home
        self._was_home = present
        if not arrived:
            return {"reported": []}

        visitors = self.faces.unreported_visitors()
        if not visitors:
            return {"reported": []}

        when = ", ".join(f"{v['time'][:5]} on {v['date']}" for v in visitors[:3])
        summary = (
            f"{len(visitors)} unrecognised "
            f"{'person' if len(visitors) == 1 else 'people'} seen while you were out ({when})"
        )
        self.journal.append(
            "vision",
            "visitor_report",
            summary,
            {"id": f"visitors-{visitors[-1]['id']}",
             "visitors": visitors,
             "thumbnails": [v["thumbnail"] for v in visitors if v["thumbnail"]]},
            trusted=True,
        )
        self.faces.mark_reported([v["id"] for v in visitors])
        return {"reported": [v["id"] for v in visitors], "summary": summary}

    def _presence(self) -> bool:
        if self.room_state is None:
            return True
        try:
            return bool(self.room_state().get("present", True))
        except Exception:
            return self._was_home

    def run_reflect(self) -> dict[str, Any]:
        if self.memory is None:
            return {"promoted": []}
        result = self.memory.reflect()
        for subject in result.get("promoted", []):
            self.journal.append("memory", "reflection", subject, {"id": subject}, trusted=True)
        return result

    def run_consolidate(self) -> dict[str, Any]:
        return self.memory.consolidate() if self.memory is not None else {"forgotten": 0}

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> bool:
        if self._scheduler is not None:
            return False
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
        scheduler.add_job(
            self._guard("ingest", self.run_ingest), "interval",
            minutes=INGEST_MINUTES, id="ingest", max_instances=1, coalesce=True,
        )
        scheduler.add_job(
            self._guard("mind", self.run_mind), "interval",
            minutes=MIND_MINUTES, id="mind", max_instances=1, coalesce=True,
        )
        scheduler.add_job(
            self._guard("homecoming", self.run_homecoming), "interval",
            minutes=1, id="homecoming", max_instances=1, coalesce=True,
        )
        scheduler.add_job(
            self._guard("reflect", self.run_reflect), "interval",
            hours=REFLECT_HOURS, id="reflect", max_instances=1, coalesce=True,
        )
        scheduler.add_job(
            self._guard("consolidate", self.run_consolidate), "interval",
            hours=CONSOLIDATE_HOURS, id="consolidate", max_instances=1, coalesce=True,
        )
        scheduler.start()
        self._scheduler = scheduler
        return True

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
