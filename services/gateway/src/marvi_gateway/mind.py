"""The mind turn.

Reads pending journal events, asks the policy how loud each one may be, and
takes the least intrusive useful action. Every turn writes a decision record —
trigger, rule, surface, provider, latency, tokens — so the user can always ask
why Marvi spoke, or why it did not.

Two properties `REAL-AGENCY.md` insists on and this module enforces:

* deciding nothing is the normal case and must be cheap. The deterministic path
  never calls a model, so an idle tick costs a few SQLite reads;
* the mind proposes; it does not act. Anything with a side effect goes back
  through the Gateway tool router, which means confirmation and audit still
  apply. The mind cannot bypass its own policy by "deciding" to.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from .journal import EventJournal
from .policy import InitiativeSettings, Verdict, WorldState, day_start, evaluate

logger = logging.getLogger(__name__)

MAX_EVENTS_PER_TURN = 10


class Mind:
    def __init__(
        self,
        journal: EventJournal,
        memory: Any = None,
        settings: InitiativeSettings | None = None,
        deliberate: Any = None,
        announcer: Any = None,
    ) -> None:
        self.journal = journal
        self.memory = memory
        self.settings = settings or InitiativeSettings()
        # `deliberate(event, verdict) -> (surface, detail, tokens)` is the seam
        # for an LLM pass. Left unset, the mind is fully deterministic.
        self.deliberate = deliberate
        # Speaks proactive sentences. Left unset, `speak` still records a
        # decision but stays silent.
        self.announcer = announcer

    # -- world ---------------------------------------------------------------

    def world(self, now: datetime, conversation_active: bool, present: bool) -> WorldState:
        return WorldState(
            now=now,
            conversation_active=conversation_active,
            present=present,
            tokens_today=self.journal.tokens_since(day_start(now)),
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
            logger.debug("mind tick idle", extra={"marvi_pending": 0})
            return {"considered": 0, "decisions": [], "surfaced": []}

        base = self.world(moment, conversation_active, present)
        decisions: list[dict[str, Any]] = []
        surfaced: list[dict[str, Any]] = []
        logger.info(
            "mind tick started",
            extra={
                "marvi_pending": len(pending),
                "marvi_conversation_active": conversation_active,
                "marvi_present": present,
                "marvi_tokens_today": base.tokens_today,
            },
        )

        for event in pending:
            started = time.perf_counter()
            world = WorldState(
                now=base.now,
                conversation_active=base.conversation_active,
                present=base.present,
                tokens_today=base.tokens_today,
                last_surfaced=self.journal.last_surfaced(event["source"], event["kind"]),
            )
            verdict = evaluate(
                event, world, self.settings, wanted=self._wanted_surface(event)
            )
            logger.info(
                "mind policy evaluated event",
                extra={
                    "marvi_event_id": event["id"],
                    "marvi_source": event["source"],
                    "marvi_kind": event["kind"],
                    "marvi_trusted": event["trusted"],
                    "marvi_rule": verdict.rule,
                    "marvi_surface_ceiling": verdict.surface,
                    "marvi_llm_eligible": bool(
                        self.deliberate is not None and verdict.allow and verdict.surface != "silent"
                    ),
                },
            )

            surface, detail, tokens, provider = verdict.surface, verdict.detail, 0, "deterministic"
            # `detail` is diagnostic text about the rule. What Marvi would
            # actually say is separate, and only deliberation can phrase it.
            sentence = event["summary"]
            if self.deliberate is not None and verdict.allow and verdict.surface != "silent":
                # An LLM may only make a decision quieter, never louder: the
                # policy ceiling is not something a model gets to argue with.
                proposed, proposed_detail, tokens = self.deliberate(event, verdict)
                from .policy import SURFACES

                if SURFACES.index(proposed) <= SURFACES.index(verdict.surface):
                    surface, detail = proposed, proposed_detail
                    if proposed_detail:
                        sentence = proposed_detail
                resolved_provider = str(getattr(self.deliberate, "last_provider", "") or "llm")
                resolved_model = str(getattr(self.deliberate, "last_model", "") or "")
                provider = (
                    f"{resolved_provider}/{resolved_model}" if resolved_model else resolved_provider
                )

            if surface == "remember" and self.memory is not None:
                body = str(event["payload"])[:2000]
                if event["trusted"]:
                    self.memory.remember(event["summary"], body, kind="episodic")
                else:
                    # Untrusted in the journal stays untrusted in memory.
                    self.memory.remember_external(
                        event["summary"], body, source=event["source"]
                    )

            spoken = ""
            if surface == "speak" and self.announcer is not None:
                outcome = self.announcer.speak(sentence)
                if outcome.get("played"):
                    spoken = sentence
                else:
                    # Losing a voice is not losing the decision; drop to the
                    # Island so the user still sees it.
                    surface = "island"
                    detail = f"{detail} (speech unavailable)".strip()

            latency = (time.perf_counter() - started) * 1000
            decision_id = self.journal.record_decision(
                trigger=event["summary"],
                surface=surface,
                rule=verdict.rule,
                detail=detail,
                event_id=event["id"],
                provider=provider,
                latency_ms=latency,
                tokens=tokens,
                outcome=("spoke: " + spoken) if spoken
                else ("surfaced" if surface not in ("silent", "remember") else surface),
                now=moment,
            )
            self.journal.mark_processed(event["id"], decision_id)
            base.tokens_today += tokens
            logger.info(
                "mind decision recorded",
                extra={
                    "marvi_event_id": event["id"],
                    "marvi_decision_id": decision_id,
                    "marvi_surface": surface,
                    "marvi_rule": verdict.rule,
                    "marvi_provider": provider,
                    "marvi_tokens": tokens,
                    "marvi_latency_ms": round(latency, 2),
                },
            )

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

        logger.info(
            "mind tick completed",
            extra={
                "marvi_considered": len(pending),
                "marvi_surfaced": len(surfaced),
                "marvi_tokens_today": base.tokens_today,
            },
        )
        return {"considered": len(pending), "decisions": decisions, "surfaced": surfaced}

    # -- explanation ----------------------------------------------------------

    def why(self, limit: int = 20) -> list[dict[str, Any]]:
        """The decision log, newest first: what happened and which rule decided."""
        return self.journal.decisions(limit=limit)


def verdict_summary(verdict: Verdict) -> str:
    return f"{verdict.surface} ({verdict.rule})"
