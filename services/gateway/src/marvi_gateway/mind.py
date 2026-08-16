"""The mind turn.

Reads pending journal events, asks the policy how loud each one may be, and
takes the least intrusive useful action. Every turn writes a decision record —
trigger, rule, surface, provider, latency, cost — so the user can always ask
why Marvi spoke, or why it did not.

Two properties `REAL-AGENCY.md` insists on and this module enforces:

* deciding nothing is the normal case and must be cheap. The deterministic path
  never calls a model, so an idle tick costs a few SQLite reads;
* the mind proposes; it does not act. Anything with a side effect goes back
  through the Gateway tool router, which means confirmation and audit still
  apply. The mind cannot bypass its own policy by "deciding" to.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from .journal import EventJournal
from .policy import InitiativeSettings, Verdict, WorldState, day_start, evaluate

MAX_EVENTS_PER_TURN = 10


class Mind:
    def __init__(
        self,
        journal: EventJournal,
        memory: Any = None,
        settings: InitiativeSettings | None = None,
        deliberate: Any = None,
    ) -> None:
        self.journal = journal
        self.memory = memory
        self.settings = settings or InitiativeSettings()
        # `deliberate(event, verdict) -> (surface, detail, cost)` is the seam
        # for an LLM pass. Left unset, the mind is fully deterministic.
        self.deliberate = deliberate

    # -- world ---------------------------------------------------------------

    def world(self, now: datetime, conversation_active: bool, present: bool) -> WorldState:
        return WorldState(
            now=now,
            conversation_active=conversation_active,
            present=present,
            spent_today=self.journal.spend_since(day_start(now)),
        )

    def _wanted_surface(self, event: dict[str, Any]) -> str:
        """The loudest surface this event would like, before policy trims it."""
        kind = f"{event.get('source')}:{event.get('kind')}"
        return self.settings.surface_ceiling.get(kind, "activity")

    # -- the turn ------------------------------------------------------------

    def tick(
        self,
        now: datetime | None = None,
        conversation_active: bool = False,
        present: bool = True,
    ) -> dict[str, Any]:
        moment = now or datetime.now(UTC)
        pending = self.journal.pending(limit=MAX_EVENTS_PER_TURN)
        if not pending:
            # The cheap, normal case: nothing happened, nothing to answer for.
            return {"considered": 0, "decisions": [], "surfaced": []}

        base = self.world(moment, conversation_active, present)
        decisions: list[dict[str, Any]] = []
        surfaced: list[dict[str, Any]] = []

        for event in pending:
            started = time.perf_counter()
            world = WorldState(
                now=base.now,
                conversation_active=base.conversation_active,
                present=base.present,
                spent_today=base.spent_today,
                last_surfaced=self.journal.last_surfaced(event["source"], event["kind"]),
            )
            verdict = evaluate(
                event, world, self.settings, wanted=self._wanted_surface(event)
            )

            surface, detail, cost, provider = verdict.surface, verdict.detail, 0.0, "deterministic"
            if self.deliberate is not None and verdict.allow and verdict.surface != "silent":
                # An LLM may only make a decision quieter, never louder: the
                # policy ceiling is not something a model gets to argue with.
                proposed, proposed_detail, cost = self.deliberate(event, verdict)
                from .policy import SURFACES

                if SURFACES.index(proposed) <= SURFACES.index(verdict.surface):
                    surface, detail = proposed, proposed_detail
                provider = "llm"

            if surface == "remember" and self.memory is not None:
                body = str(event["payload"])[:2000]
                if event["trusted"]:
                    self.memory.remember(event["summary"], body, kind="episodic")
                else:
                    # Untrusted in the journal stays untrusted in memory.
                    self.memory.remember_external(
                        event["summary"], body, source=event["source"]
                    )

            latency = (time.perf_counter() - started) * 1000
            decision_id = self.journal.record_decision(
                trigger=event["summary"],
                surface=surface,
                rule=verdict.rule,
                detail=detail,
                event_id=event["id"],
                provider=provider,
                latency_ms=latency,
                cost=cost,
                outcome="surfaced" if surface not in ("silent", "remember") else surface,
                now=moment,
            )
            self.journal.mark_processed(event["id"], decision_id)
            base.spent_today += cost

            record = {
                "id": decision_id,
                "event": event["summary"],
                "surface": surface,
                "rule": verdict.rule,
                "detail": detail,
                "latency_ms": round(latency, 2),
            }
            decisions.append(record)
            if surface not in ("silent", "remember"):
                surfaced.append(record)

        return {"considered": len(pending), "decisions": decisions, "surfaced": surfaced}

    # -- explanation ----------------------------------------------------------

    def why(self, limit: int = 20) -> list[dict[str, Any]]:
        """The decision log, newest first: what happened and which rule decided."""
        return self.journal.decisions(limit=limit)


def verdict_summary(verdict: Verdict) -> str:
    return f"{verdict.surface} ({verdict.rule})"
