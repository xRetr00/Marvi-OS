"""Scheduled initiative.

APScheduler 3.x drives four bounded ticks. None of them touch the voice path:
they run on the scheduler's own threads and talk to SQLite and HTTP clients
that the foreground never waits on.

    ingest      pull new account items into the journal
    mind        decide what, if anything, to do about pending events
    reflect     promote repeated episodes into durable facts
    dream       conclude across memories, and build the graph from them
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

STARTUP_GRACE = 90.0
INGEST_MINUTES = 10
MIND_MINUTES = 2
REFLECT_HOURS = 6
#: Slower than reflection on purpose. Reflection is a GROUP BY; this is a model
#: reading eighty memories, and there is nothing to conclude from a morning.
DREAM_HOURS = 12
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
        auxiliary_client: Any = None,
        room_state: Any = None,
        activity: Any = None,
    ) -> None:
        self.mind = mind
        self.journal = journal
        self.ingest = ingest
        self.memory = memory
        self.memory_summarise = memory_summarise
        # The model that dreams. None is normal -- no auxiliary configured
        # means the deterministic passes still run and this one does not.
        self.auxiliary_client = auxiliary_client
        self.room_state = room_state
        # Desktop activity. None is normal -- ActivityWatch is optional, and
        # the mind decides without it exactly as it did before.
        self.activity = activity
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
                # On disk too: `last_runs` dies with the process, and the slow
                # passes are scheduled from when they last finished so that a
                # restart does not put them off by another whole interval.
                self._mark_ran(name)
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
        # What the desktop is doing, which is the signal the room cannot give.
        #
        # `activity.py` says in its own docstring that the focused window is
        # "genuinely useful context for 'is now a good moment to interrupt'",
        # and it was registered only as tools the model could call -- so the
        # thing that decides whether to interrupt never read it.
        at_machine, doing = None, ""
        if self.activity is not None:
            try:
                context = self.activity.world_context()
                idle = context.get("idle")
                at_machine = None if idle is None else not idle
                doing = str(context.get("summary") or "")
            except Exception as exc:
                logger.info(
                    "initiative desktop-activity read failed; deciding without it",
                    extra={"marvi_job": "mind", "marvi_error": str(exc)[:200]},
                )
        return self.mind.tick(
            conversation_active=conversation,
            present=present,
            at_machine=at_machine,
            doing=doing,
        )

    def run_reflect(self) -> dict[str, Any]:
        if self.memory is None:
            return {"promoted": []}
        result = self.memory.reflect(summarise=self.memory_summarise)
        for subject in result.get("promoted", []):
            self.journal.append("memory", "reflection", subject, {"id": subject}, trusted=True)
        return result

    def _own_store(self) -> Any:
        """A connection to the memory database for this thread."""
        path = getattr(self.memory, "path", None)
        if path is None:
            return self.memory
        from .memory import MemoryStore

        return MemoryStore(path)

    def run_dream(self) -> dict[str, Any]:
        """Read across what has arrived, conclude, and relate.

        Reflection counts repeats of one subject and cannot see that two things
        that each happened once say a third together. This is that pass, and it
        is where the entity graph gets built -- it had stayed empty because
        filling it was left to a model choosing `memory_link` mid-conversation,
        which no model ever did while it had an answer to give instead.
        """
        from . import dreaming

        if self.memory is None or self.auxiliary_client is None:
            return {"concluded": 0, "linked": 0, "retired": 0}
        # A private connection, the way the after-turn worker takes one. This
        # runs on a scheduler thread and writes a great deal more than the
        # other jobs; sharing the foreground's connection is what crashed the
        # process the last time a background thread wrote memories.
        store = self._own_store()
        fresh = store.undreamt(limit=dreaming.WINDOW)
        if len(fresh) < dreaming.MIN_PREMISES:
            return {"concluded": 0, "linked": 0, "retired": 0, "considered": len(fresh)}

        # Before dreaming rather than after: a conclusion is drawn from what
        # the model is shown, and what it is shown is chosen by a search.
        try:
            from . import rephrasing

            rephrasing.run(store, self.auxiliary_client)
        except Exception as exc:
            logger.warning("rephrasing failed; dreaming anyway: %s", exc)

        found = dreaming.dream(self.auxiliary_client, fresh, store.conclusions())
        counts = dreaming.apply(store, found) if found else {
            "concluded": 0, "linked": 0, "retired": 0
        }
        # The watermark moves whether or not anything was concluded. A dream
        # that found nothing has still read these, and re-reading them every
        # twelve hours would pay for the same silence forever.
        store.record_dream(
            through_id=max(int(row["id"]) for row in fresh),
            considered=len(fresh),
            **counts,
        )
        for item in (found.get("conclusions") if found else []) or []:
            self.journal.append(
                "memory", "conclusion", item["subject"], {"from": item["premises"]}, trusted=False
            )
        logger.info(
            "dreaming completed",
            extra={"marvi_considered": len(fresh), **{f"marvi_{k}": v for k, v in counts.items()}},
        )
        return {"considered": len(fresh), **counts}

    def run_rephrase(self) -> dict[str, Any]:
        """Give memories the words they would be asked for. Off unless asked.

        On the dreaming tick because it is the same kind of work -- a model
        reading what has accumulated, off the critical path, nothing waiting.
        It changes no memory: only the text used to compute the vector. See
        `rephrasing.py` for why that distinction is the whole feature.
        """
        from . import rephrasing

        if self.memory is None or self.auxiliary_client is None:
            return {"considered": 0, "enriched": 0}
        return rephrasing.run(self._own_store(), self.auxiliary_client)

    def run_consolidate(self) -> dict[str, Any]:
        """The sleep pass: memory forgets, and skills are set aside.

        Both on the same tick because they are the same job on different
        stores -- what has not been used in long enough to keep carrying. The
        sweep touches only skills Marvi wrote herself and archives rather than
        deletes; the details are in `setup/skill_usage.py`.
        """
        from .setup import skill_usage

        forgotten = self.memory.consolidate() if self.memory is not None else {"forgotten": 0}
        try:
            swept = skill_usage.sweep()
        except Exception as exc:
            logger.warning("skill sweep failed: %s", exc)
            swept = {"archived": [], "stale": []}
        for name in swept["archived"]:
            self.journal.append("skills", "archived", name, {"name": name}, trusted=True)
        return {**forgotten, "skills_archived": swept["archived"]}

    # -- lifecycle -----------------------------------------------------------

    def _ran_at(self) -> dict[str, float]:
        """When each slow job last finished, across restarts."""
        from .paths import root

        try:
            import json

            return json.loads((root() / "state" / "initiative.json").read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def _mark_ran(self, job: str) -> None:
        import json

        from .paths import root

        path = root() / "state" / "initiative.json"
        seen = self._ran_at()
        seen[job] = time.time()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(seen), encoding="utf-8")
        except OSError as exc:  # pragma: no cover - depends on the filesystem
            logger.warning("could not record when %s ran: %s", job, exc)

    def _first_run(self, job: str, every_seconds: float) -> Any:
        """When this job should next run, counting from when it last did.

        APScheduler's interval trigger counts from when the *scheduler* starts,
        so a twelve-hour job needs twelve hours of unbroken uptime. Measured on
        this installation: the Gateway restarts every twelve minutes at the
        median and its longest run on record is five hours, so `dream` and
        `consolidate` had never executed -- not late, not skipped, zero runs
        since they were written. Every slow pass in the memory architecture was
        dead code in production while looking scheduled.

        Counting from the last completed run instead means a restart costs
        nothing, and a job that is overdue runs shortly after boot rather than
        one whole interval later.
        """
        from datetime import UTC, datetime, timedelta

        last = self._ran_at().get(job)
        if last is None:
            # Never run. Soon, but not during boot -- these are model calls and
            # the first minute after start belongs to whoever is waiting.
            return datetime.now(UTC) + timedelta(seconds=STARTUP_GRACE)
        due = last + every_seconds
        return datetime.fromtimestamp(max(due, time.time() + STARTUP_GRACE), UTC)

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
            next_run_time=self._first_run("reflect", REFLECT_HOURS * 3600),
        )
        scheduler.add_job(
            self._guard("dream", self.run_dream), "interval",
            hours=DREAM_HOURS, id="dream", max_instances=1, coalesce=True,
            next_run_time=self._first_run("dream", DREAM_HOURS * 3600),
        )
        scheduler.add_job(
            self._guard("consolidate", self.run_consolidate), "interval",
            hours=CONSOLIDATE_HOURS, id="consolidate", max_instances=1, coalesce=True,
            next_run_time=self._first_run("consolidate", CONSOLIDATE_HOURS * 3600),
        )
        scheduler.start()
        self._scheduler = scheduler
        logger.info(
            "initiative scheduler started",
            extra={
                "marvi_ingest_minutes": INGEST_MINUTES,
                "marvi_mind_minutes": MIND_MINUTES,
                "marvi_reflect_hours": REFLECT_HOURS,
                "marvi_dream_hours": DREAM_HOURS,
                "marvi_consolidate_hours": CONSOLIDATE_HOURS,
            },
        )
        return True

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("initiative scheduler stopped")
