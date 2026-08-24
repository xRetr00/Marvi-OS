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
import time
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
        memory_summarise: Any = None,
        room_state: Any = None,
    ) -> None:
        self.mind = mind
        self.journal = journal
        self.ingest = ingest
        self.memory = memory
        self.memory_summarise = memory_summarise
        self.room_state = room_state
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
            "settings": self.mind.settings.as_dict(),
        }

    # -- jobs ----------------------------------------------------------------

    def _guard(self, name: str, work: Any) -> Any:
        def run() -> None:
            started = time.perf_counter()
            logger.info("initiative job started", extra={"marvi_job": name})
            try:
                result = work()
                self.last_runs[name] = datetime.now(UTC).isoformat()
                self.last_errors.pop(name, None)
                logger.info(
                    "initiative job completed",
                    extra={
                        "marvi_job": name,
                        "marvi_latency_ms": round((time.perf_counter() - started) * 1000, 2),
                        "marvi_result_keys": ",".join(sorted(result))
                        if isinstance(result, dict)
                        else type(result).__name__,
                    },
                )
            except Exception as exc:
                self.last_errors[name] = str(exc)[:200]
                logger.warning(
                    "initiative job failed",
                    extra={
                        "marvi_job": name,
                        "marvi_latency_ms": round((time.perf_counter() - started) * 1000, 2),
                        "marvi_error": str(exc)[:240],
                    },
                    exc_info=True,
                )

        return run

    def run_ingest(self) -> dict[str, Any]:
        """Pull account items and journal them. Ingestion runs even when paused
        so nothing is lost; only decisions stop."""
        if self.ingest is None:
            return {"ingested": []}
        result = self.ingest.poll()
        events = result.get("events", [])
        if events:
            for event in events:
                toolkit = str(event.get("toolkit", "account"))
                self.journal.append(
                    f"accounts:{toolkit}",
                    toolkit,
                    str(event.get("subject", toolkit)),
                    event,
                    trusted=False,
                )
        else:
            # Compatibility with third-party/older ingestion adapters.
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
            except Exception as exc:
                logger.warning(
                    "initiative room-state read failed; using present/idle defaults",
                    extra={"marvi_job": "mind", "marvi_error": str(exc)[:240]},
                    exc_info=True,
                )
        return self.mind.tick(conversation_active=conversation, present=present)

    def run_reflect(self) -> dict[str, Any]:
        if self.memory is None:
            return {"promoted": []}
        result = self.memory.reflect(summarise=self.memory_summarise)
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
            self._guard("reflect", self.run_reflect), "interval",
            hours=REFLECT_HOURS, id="reflect", max_instances=1, coalesce=True,
        )
        scheduler.add_job(
            self._guard("consolidate", self.run_consolidate), "interval",
            hours=CONSOLIDATE_HOURS, id="consolidate", max_instances=1, coalesce=True,
        )
        scheduler.start()
        self._scheduler = scheduler
        logger.info(
            "initiative scheduler started",
            extra={
                "marvi_ingest_minutes": INGEST_MINUTES,
                "marvi_mind_minutes": MIND_MINUTES,
                "marvi_reflect_hours": REFLECT_HOURS,
                "marvi_consolidate_hours": CONSOLIDATE_HOURS,
            },
        )
        return True

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("initiative scheduler stopped")
