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

import contextlib
import logging
import time
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

STARTUP_GRACE = 90.0
INGEST_MINUTES = 10
MIND_MINUTES = 2
#: How often the machine looks at itself. Cheap enough to do often -- no model,
#: no network beyond one DNS lookup -- and a disk filling up is worth knowing
#: about before the thing that needed the space fails.
MACHINE_MINUTES = 5

#: How often Marvi checks herself over.
#:
#: Doctor only ever ran when somebody asked -- `/doctor`, or `marvi doctor` in
#: a terminal. So a missing espeak backend, a camera with no driver, a browser
#: engine that was never downloaded all sat there being wrong, and the way you
#: found out was noticing Marvi behaving oddly and going to read a log.
#:
#: That is the wrong shape for this kind of failure. A missing config flag can
#: wait for somebody to look; a missing dependency has already stopped a whole
#: capability and will not fix itself.
#:
#: Twenty minutes, not one: the checks shell out and one of them launches
#: Chromium. Frequent enough that a thing broken at breakfast is not still
#: undiscovered at lunch, rare enough to be free.
SELF_CHECK_MINUTES = 20
#: How often a resource reading is taken. Thirty seconds: the readings that
#: matter are taken on phase changes rather than on this timer, so this only
#: has to be often enough to draw a line between them.
ACCOUNTING_SECONDS = 30
#: How often she checks whether there is something worth asking about.
#:
#: Four hours, and `Curiosity` has a cooldown of its own on top, so the real
#: rate is far lower. A question is the most intrusive thing she can offer
#: unprompted -- it wants an answer -- so this is deliberately the slowest job
#: on the scheduler.
CURIOSITY_HOURS = 4
#: How often the foreground app is checked. Shorter than the machine watch:
#: standing off the GPU is only useful if it happens while the game is still
#: loading, and `focus.SETTLED_LOOKS` means two of these before it acts.
FOCUS_MINUTES = 1
#: Rain warnings look three hours ahead; twenty minutes keeps the lead honest.
WEATHER_MINUTES = 20
REFLECT_HOURS = 6
#: Slower than reflection on purpose. Reflection is a GROUP BY; this is a model
#: reading eighty memories, and there is nothing to conclude from a morning.
DREAM_HOURS = 12
CONSOLIDATE_HOURS = 24
#: The storage pass. Daily; it cycles logs itself only every third day.
STORAGE_HOURS = 24


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
        waiting: Any = None,
    ) -> None:
        self.mind = mind
        # Handed to the mind rather than held here: it is the mind that
        # decides something cannot be said yet, and the mind that asks again.
        if waiting is not None:
            mind.waiting = waiting
            # So the mind can decline to cold-load the voice mid-game.
            mind.busy_with = lambda: (
                getattr(self.focus, "because", "") if self.focus is not None else ""
            )
            # The same model the gatekeeper uses on the way in, for the items
            # that arrived while it was unavailable.
            if auxiliary_client is not None:
                from .gatekeeping import what_it_says

                mind.read_late = lambda subject, body: what_it_says(
                    auxiliary_client, subject, body, mind._name()
                )
                # So a cooldown is waited out rather than walked into. The
                # harness wraps a `ProviderClient`; reach through to it, and
                # leave the hook unset if this one does not.
                inner = getattr(auxiliary_client, "client", auxiliary_client)
                if hasattr(inner, "soonest_available"):
                    mind.models_resting = inner.soonest_available
        self.journal = journal
        self.ingest = ingest
        #: Built on first use, because it holds the last reading and a fresh
        #: one would report every threshold again on every restart.
        self._machine: Any = None
        #: Notices a feeder that has stopped talking. See `quiet_feeds`.
        self._quiet_feeds: Any = None
        #: Watches the foreground app and holds the resource mode. Shared with
        #: the route the agent asks before it takes the GPU.
        self.focus: Any = None
        self.memory = memory
        self.memory_summarise = memory_summarise
        # The model that dreams. None is normal -- no auxiliary configured
        # means the deterministic passes still run and this one does not.
        self.auxiliary_client = auxiliary_client
        self.room_state = room_state
        #: `(easy: bool) -> None` -- tell the room to stand down for a game.
        #: Left unset, the room simply carries on as it always did.
        self.pace_the_room: Any = None
        #: `accounting.Accountant`, when one is wired. Left unset, nothing is
        #: recorded and everything else behaves exactly as it did.
        self.books: Any = None
        #: `location.LocationService`, for weather warnings. Left unset, none.
        self.weather: Any = None
        self._weather_watch: Any = None
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
            # What the page actually needs to answer "why is she quiet".
            #
            # Pause, running and a pending count say whether the machinery is
            # turning. They do not say whether Marvi *would* speak, which is
            # the only question anybody opens this page with -- and the answer
            # is usually a perfectly ordinary reason nothing was surfacing it.
            "quiet_because": self._quiet_because(),
            "waiting": self.mind.waiting.waiting() if self.mind.waiting else [],
            "feeders": self._feeders(),
        }

    def _quiet_because(self) -> str:
        """The reason she would not speak right now, or empty if she would."""
        from datetime import datetime as _dt

        from .policy import _quiet_now, day_start

        if self.paused:
            return "initiative is switched off"
        settings = self.mind.settings
        if _quiet_now(settings, _dt.now(UTC)):
            return f"quiet hours, until {settings.quiet_end:02d}:00"
        world = self._world_now()
        if world.get("conversation_active"):
            return "you are in a call"
        if not world.get("present", True):
            return "nobody seems to be here"
        if self.focus is not None and getattr(self.focus, "low_resource", False):
            return f"{self.focus.because} is running"
        spent = self.journal.tokens_since(day_start(datetime.now(UTC)))
        if spent >= settings.daily_token_budget:
            return f"the day's thinking budget is spent ({spent:,} tokens)"
        return ""

    def _world_now(self) -> dict[str, Any]:
        if self.room_state is None:
            return {}
        try:
            return dict(self.room_state() or {})
        except Exception:
            return {}

    def _feeders(self) -> list[dict[str, Any]]:
        """Everything that can put something in front of the mind, and whether
        it is actually doing so.

        A feeder that quietly stopped feeding is invisible: the page shows the
        mind turning happily on nothing at all, which is what "Mind is not
        minding" looked like from the outside for weeks.
        """
        counts = {}
        recent: dict[str, list[str]] = {}
        try:
            counts = dict(self.journal.counts_by_source() or {})
            # What those events actually were.
            #
            # "This machine: 2" is a number with nothing behind it, and the
            # page could not answer the obvious next question. Two summaries
            # per feeder is enough to recognise them and small enough to ride
            # the status poll.
            for row in self.journal.recent(limit=120):
                key = str(row.get("source") or "")
                bucket = key.split(":")[0]
                if len(recent.setdefault(bucket, [])) < 3:
                    recent[bucket].append(str(row.get("summary") or "")[:120])
        except Exception:
            counts = counts or {}
        rows = [
            ("room", "Room and vision", self.room_state is not None),
            ("machine", "This machine", self._machine is not None),
            ("focus", "What you are doing", self.focus is not None),
            ("accounts", "Connected accounts", self.ingest is not None),
            ("schedule", "Your schedules", True),
            ("weather", "Weather where you are", self.weather is not None),
        ]
        return [
            {
                "id": key,
                "label": label,
                "wired": bool(wired),
                # Prefixes, because accounts are journalled as
                # `accounts:gmail` and the row is about accounts as a whole.
                "events": sum(n for source, n in counts.items() if source.startswith(key)),
                "examples": recent.get(key, []),
            }
            for key, label, wired in rows
        ]

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

    def run_focus(self) -> dict[str, Any]:
        """Notice a game starting or finishing. See `focus`."""
        if self.journal is None or self.focus is None:
            return {"noticed": 0}
        changes = self.focus.look()
        if changes and self.pace_the_room is not None:
            # The room is the only part of Marvi that works hard when nobody
            # is asking it anything -- a capture loop with no delay in it and
            # MediaPipe on every frame it keeps -- so it is the part that has
            # to be told a game started. Everything else here waits on a timer.
            easy = changes[-1].kind == "heavy_app_started"
            try:
                self.pace_the_room(easy)
            except Exception as exc:
                logger.info("could not pace the room (%s)", str(exc)[:160])
        if changes and self.books is not None:
            # The single most useful reading in the file: what she was holding
            # at the moment a match began, and what she had let go of a minute
            # later. Taken here rather than on the timer because a thirty
            # second tick walks straight past both.
            self.books.told(
                low_resource=changes[-1].kind == "heavy_app_started",
                busy_with=str(changes[-1].payload.get("name", "")),
                moment="game" if changes[-1].kind == "heavy_app_started" else "",
            )
        for change in changes:
            # `Focus.look` only speaks on a transition -- it holds a candidate
            # still for two looks and returns nothing while the state is
            # unchanged -- so the journal's own repetition guard has nothing
            # left to catch here and only ever swallows a real second launch.
            self.journal.append(
                "focus", change.kind, change.summary, change.payload,
                trusted=True, dedupe=False,
            )
        return {"noticed": len(changes)}

    def run_curiosity(self) -> dict[str, Any]:
        """Ask about something she does not know, when there is a good moment.

        Curiosity has always been able to name a gap -- `may_ask` returns one
        thing worth asking and `None` the rest of the time -- and nothing ever
        asked it outside a turn. So she noticed things while being spoken to
        and never went looking, which is most of the difference between an
        assistant and a form.

        The gap becomes an event and the mind decides the rest: presence, the
        hour, whether she has just spoken, whether it is worth a word. This job
        only says there is something worth asking.
        """
        if self.journal is None:
            return {"asked": 0}
        try:
            from .curiosity import Curiosity
        except Exception:
            return {"asked": 0}
        try:
            wondering = Curiosity()
        except Exception as exc:
            logger.info("could not open curiosity (%s)", str(exc)[:120])
            return {"asked": 0}
        try:
            # `turns_this_session` guards against asking in the first breath of
            # a conversation. Out here there is no conversation, so the guard
            # does not apply and its own cooldown is what spaces these out.
            gap = wondering.may_ask(turns_this_session=99)
            if gap is None:
                return {"asked": 0}
            self.journal.append(
                "curiosity",
                "question",
                f"Ask about {gap.prompt}.",
                {"key": gap.key, "heading": gap.heading, "says": f"Ask about {gap.prompt}."},
                trusted=True,
                dedupe=False,
            )
            wondering.mark_asked(gap.key)
            logger.info("wondering about %s", gap.key, extra={"marvi_gap": gap.key})
            return {"asked": 1, "gap": gap.key}
        finally:
            with contextlib.suppress(Exception):
                wondering.close()

    def run_accounting(self) -> dict[str, Any]:
        """Take a reading. See `accounting`."""
        if self.books is None:
            return {"read": 0}
        self.books.look()
        return {"read": 1}

    def run_quiet_feeds(self) -> dict[str, Any]:
        """Notice a source that has stopped talking. See `quiet_feeds`.

        Rides the machine watch's interval rather than its own: this fires on
        the *absence* of events, so there is nothing to be prompt about.
        """
        if self.journal is None or self.room_state is None:
            return {"quiet": 0}
        if self._quiet_feeds is None:
            from .quiet_feeds import Watcher

            self._quiet_feeds = Watcher()
        try:
            from . import presence, quiet_feeds

            state = (self.room_state() or {}).get("state") or {}
            if not state:
                # No room to read. Not the same as a quiet room, and warning
                # about four silent feeds because the sidecar is down would be
                # four ways of saying one thing.
                return {"quiet": 0}
            ages = quiet_feeds.ages_from(presence.signals(state))
        except Exception as exc:
            logger.info("could not check for quiet feeds (%s)", str(exc)[:160])
            return {"quiet": 0}

        found = self._quiet_feeds.look(ages)
        for gone in found:
            self.journal.append(
                "system",
                "feed_quiet",
                gone.sentence(),
                {"feed": gone.feed.id, "silent_seconds": round(gone.silent_for)},
                trusted=True,
            )
        return {"quiet": len(found)}

    def run_self_check(self) -> dict[str, Any]:
        """Run the doctor unasked, fix what is safe, and say what is not.

        Three things, in the order they matter:

        * **Heal what heals itself.** `heal` applies only the `automatic`
          remedies; a `confirm` one -- anything that downloads, deletes or
          costs -- is deliberately left for a person. That split already
          existed and nothing was calling it.
        * **Say what stopped.** A dependency that breaks a capability goes to
          the announcer through the component status, which is the channel
          that still works when the rest does not.
        * **Record it.** So `/doctor` shows the same findings without waiting
          for somebody to press it.
        """
        from . import doctor

        findings = doctor.run_checks()
        broken = [f for f in findings if f.status == "fail"]
        warned = [f for f in findings if f.status == "warn"]

        healed: list[dict[str, Any]] = []
        if fixable := [f for f in findings if f.fixable]:
            # `include_confirmed=False`: never the ones that download or
            # destroy. Those are a person's decision and stay one.
            healed = doctor.heal(fixable, include_confirmed=False)
            for entry in healed:
                logger.info("self check fixed something", extra={"marvi_fix": str(entry)})

        for finding in broken + warned:
            logger.warning(
                "self check: %s", finding.detail,
                extra={"marvi_check": finding.check, "marvi_area": finding.area},
            )
        return {
            "checked": len(findings),
            "failing": len(broken),
            "warnings": len(warned),
            "healed": len(healed),
        }

    def run_machine(self) -> dict[str, Any]:
        """Let the machine notice its own condition. See `machine`.

        Trusted, unlike everything else that arrives from outside: nobody but
        this process wrote these numbers, so there is no stranger's text in
        them and no reason to hold them at arm's length.
        """
        if self.journal is None:
            return {"noticed": 0}
        if self._machine is None:
            from .machine import Machine
            from .paths import root as _state_root

            # On disk, so a restart does not re-announce a disk that is still
            # as full as it was five minutes ago.
            self._machine = Machine(_state_root() / "state" / "machine.json")
        # What has the machine, if anything. Memory pressure during a game is
        # the game, and saying so is complaining about the thing she just
        # stood aside for.
        busy = getattr(self.focus, "because", "") if self.focus is not None else ""
        readings = self._machine.look(busy_with=busy)
        for reading in readings:
            if reading.kind in ("disk_low", "disk_critical"):
                self._make_room(reading.payload)
            self.journal.append(
                "machine", reading.kind, reading.summary, reading.payload, trusted=True
            )
        return {"noticed": len(readings)}

    def run_storage(self) -> dict[str, Any]:
        """Throw away what regenerates. See `storage`."""
        from . import storage

        report = storage.housekeep()
        return {"freed_bytes": report["freed_bytes"], "removed": len(report["removed"])}

    def _make_room(self, payload: dict[str, Any]) -> None:
        """A disk just went low: clean now, and say what is left to take.

        Only for the drive Marvi lives on -- cleaning her folder does nothing
        for a full D:. The unused engines are sized, not removed: they are a
        download to get back, so the sentence offers and a person decides.
        """
        from . import storage
        from .paths import root

        if str(payload.get("drive", "")).upper() != root().anchor[:1].upper():
            return
        try:
            payload["freed_gb"] = round(storage.housekeep()["freed_bytes"] / 1024**3, 1)
            unused = sum(held for _c, _w, held in storage.unused_engines())
            payload["reclaimable_gb"] = round(unused / 1024**3, 1)
        except Exception as exc:
            logger.info("could not make room on a low disk (%s)", str(exc)[:160])

    def run_weather(self) -> dict[str, Any]:
        """Warn about rain, snow, storms, cold, heat, UV and wind. See `weather_watch`.

        Reads the forecast `LocationService` already caches, so this adds at
        most one Open-Meteo request per ten minutes, and only with a location.
        """
        if self.journal is None or self.weather is None:
            return {"warned": 0}
        data = self.weather.weather().get("data")
        if not data or not data.get("hourly", {}).get("time"):
            return {"warned": 0}
        from . import weather_watch
        from .paths import root as _state_root

        if self._weather_watch is None:
            self._weather_watch = weather_watch.WeatherWatch(_state_root() / "state" / "weather.json")
        place = (self.weather.status().get("place") or {}).get("label", "")
        fresh = self._weather_watch.fresh(weather_watch.alerts(data))
        for alert in fresh:
            self.journal.append(
                "weather", alert["kind"], weather_watch.summary(alert),
                {**alert, "place": place}, trusted=True, dedupe=False,
            )
        return {"warned": len(fresh)}

    def run_mind(self) -> dict[str, Any]:
        present, conversation, asleep = True, False, False
        if self.room_state is not None:
            try:
                snapshot = self.room_state()
                present = bool(snapshot.get("present", True))
                conversation = bool(snapshot.get("conversation_active", False))
                asleep = bool(snapshot.get("asleep", False))
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
            asleep=asleep,
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
            # The conclusion itself, not just its title.
            #
            # This journalled `item["subject"]` -- "Shereef's greeting
            # preference context" -- and nothing downstream could turn that
            # into a sentence, because it is not one. The thing she worked out
            # is in `body`, and it is the whole point:
            #
            #     "Shereef prefers 'good morning' over 'good night' because
            #      his sleep schedule involves going to sleep in the morning"
            #
            # She concluded that at 01:37 and it went to the activity feed,
            # the night before a conversation spent correcting her about
            # exactly it.
            said = str(item.get("body") or "").strip() or str(item["subject"])
            self.journal.append(
                "memory",
                "conclusion",
                said[:300],
                {
                    "subject": item["subject"],
                    "says": said,
                    "from": item["premises"],
                },
                trusted=False,
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
            self._guard("focus", self.run_focus), "interval",
            minutes=FOCUS_MINUTES, id="focus", max_instances=1, coalesce=True,
        )
        scheduler.add_job(
            self._guard("machine", self.run_machine), "interval",
            minutes=MACHINE_MINUTES, id="machine", max_instances=1, coalesce=True,
        )
        scheduler.add_job(
            self._guard("curiosity", self.run_curiosity), "interval",
            hours=CURIOSITY_HOURS, id="curiosity", max_instances=1, coalesce=True,
            next_run_time=self._first_run("curiosity", CURIOSITY_HOURS * 3600),
        )
        scheduler.add_job(
            self._guard("self_check", self.run_self_check), "interval",
            minutes=SELF_CHECK_MINUTES, id="self_check", max_instances=1, coalesce=True,
        )
        scheduler.add_job(
            self._guard("accounting", self.run_accounting), "interval",
            seconds=ACCOUNTING_SECONDS, id="accounting", max_instances=1, coalesce=True,
        )
        scheduler.add_job(
            self._guard("quiet_feeds", self.run_quiet_feeds), "interval",
            minutes=MACHINE_MINUTES, id="quiet_feeds", max_instances=1, coalesce=True,
        )
        scheduler.add_job(
            self._guard("weather", self.run_weather), "interval",
            minutes=WEATHER_MINUTES, id="weather", max_instances=1, coalesce=True,
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
        scheduler.add_job(
            self._guard("storage", self.run_storage), "interval",
            hours=STORAGE_HOURS, id="storage", max_instances=1, coalesce=True,
            next_run_time=self._first_run("storage", STORAGE_HOURS * 3600),
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
