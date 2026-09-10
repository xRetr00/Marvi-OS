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
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from . import salience
from .journal import EventJournal
from .policy import (
    SURFACES,
    InitiativeSettings,
    Verdict,
    WorldState,
    day_start,
    evaluate,
    must_be_said,
)

logger = logging.getLogger(__name__)

MAX_EVENTS_PER_TURN = 10


#: The quietest visible surface. Nothing below this is worth a model call.
QUIETEST_VISIBLE = "activity"


def _cap_to_activity(surface: str) -> str:
    """The loudest a repetitive event may be: seen, never announced."""
    from .policy import SURFACES

    if SURFACES.index(surface) <= SURFACES.index(QUIETEST_VISIBLE):
        return surface
    return QUIETEST_VISIBLE


def _worth_thinking_about(verdict: Any) -> bool:
    """Whether deliberation could change this outcome, rather than confirm it.

    An LLM may only make a decision *quieter* -- the policy ceiling is not
    something a model gets to argue with. So for an event the policy has
    already capped at `activity`, the loudest thing the model can propose is
    what is already going to happen, and the only other option is silence.
    Paying nine hundred tokens for that is the definition of spending the
    budget on nothing.

    Measured on the owner's machine, over 200 decisions: 102,021 tokens across
    122 calls, of which

        Awake                     31,954   31.3%
        Unknown visitor seen      29,966   29.4%
        Sleep state changed       24,798   24.3%

    -- 85% spent on three room sensors, every one of them ending `silent`, and
    the exhausted budget then silenced 22 of the 23 real calendar events behind
    them. Two of those three are now capped `silent` outright; this is what
    stops the third, and anything like it, from buying a model call to confirm
    a floor it cannot move off.
    """
    from .policy import SURFACES

    if verdict.surface == "silent":
        return False
    return SURFACES.index(verdict.surface) > SURFACES.index(QUIETEST_VISIBLE)


def _readable(payload: Any) -> str:
    """A payload as a sentence, rather than as a Python repr.

    A dict becomes "from: ahmed@example.com; subject: Invoice", which a keyword
    search can match and a person can read. `str(dict)` becomes
    `{'id': 'User shared a link'}`, which neither can.
    """
    if isinstance(payload, dict):
        parts = [
            f"{key}: {value}"
            for key, value in payload.items()
            if value not in (None, "", [], {}) and not isinstance(value, dict | list)
        ]
        if parts:
            return "; ".join(parts)
    if isinstance(payload, str):
        return payload
    return str(payload) if payload else ""


class Mind:
    def __init__(
        self,
        journal: EventJournal,
        memory: Any = None,
        settings: InitiativeSettings | None = None,
        deliberate: Any = None,
        announcer: Any = None,
        identity: Any = None,
        presence: Any = None,
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
        #: Where things go that were worth saying and could not be said yet.
        #: Left unset, nothing is held and the old behaviour returns exactly.
        self.waiting: Any = None
        #: `() -> str` -- what has the machine, when something does. Left
        #: unset, nothing is ever held for it.
        self.busy_with: Any = lambda: ""
        #: Reads a held item that arrived while no model would answer.
        #: `(subject, body) -> one sentence`. See `gatekeeping.what_it_says`.
        self.read_late: Any = None
        #: Seconds until a model will answer; 0 when one will now. Consulted
        #: before `read_late`, so a cooldown is *waited out* rather than walked
        #: into every couple of minutes. See `ProviderClient.soonest_available`.
        self.models_resting: Any = None
        # Who she is talking to, for the name in what she says. Left unset,
        # every line still reads correctly -- see `voicing`.
        self.identity = identity
        # `presence() -> bool | None`: whether the person is somewhere other
        # than home. Only "someone is in the room" depends on it, and only
        # because that sentence means something else entirely when you are out.
        self.presence = presence
        #: `(sentence, event) -> bool`: say it on the phone instead. Consulted
        #: only when the one reason not to speak was an empty room -- quiet
        #: hours, a live call and the budget still mean silence. False means it
        #: could not be sent, and the item is held exactly as before.
        self.messenger: Any = None

    # -- how it sounds -------------------------------------------------------

    def _out_loud(self, event: dict[str, Any]) -> str:
        """The spoken phrasing for this event, if `voicing` has one.

        Defensive throughout: this exists to make Marvi sound human, and
        failing to phrase something warmly must never stop it being said.
        """
        try:
            from . import voicing

            return voicing.spoken(event, self._name(), away=self._away())
        except Exception:
            return ""

    def _name(self) -> str:
        """What to call them, from `USER.md`. Empty reads fine everywhere."""
        try:
            from . import voicing

            return voicing.name_of(self.identity.user_path.read_text(encoding="utf-8"))
        except Exception:
            return ""

    def _away(self) -> bool | None:
        try:
            return self.presence() if self.presence is not None else None
        except Exception:
            return None

    # -- world ---------------------------------------------------------------

    def world(
        self,
        now: datetime,
        conversation_active: bool,
        present: bool,
        at_machine: bool | None = None,
        doing: str = "",
    ) -> WorldState:
        return WorldState(
            now=now,
            conversation_active=conversation_active,
            present=present,
            tokens_today=self.journal.tokens_since(day_start(now)),
            at_machine=at_machine,
            doing=doing,
        )

    def _wanted_surface(self, event: dict[str, Any]) -> str:
        """The loudest surface this event would like, before policy trims it."""
        kind = f"{event.get('source')}:{event.get('kind')}"
        return self.settings.surface_ceiling.get(kind, "activity")

    # -- the turn ------------------------------------------------------------

    def say_waiting(self, summary: str = "") -> str:
        """Say one held item out loud now. Returns what was said, or "".

        Bypasses the timing rules deliberately -- the person asked, and their
        asking is better evidence that this is a good moment than any estimate
        of one. Everything else still applies: it is still phrased by
        `voicing`, and an untrusted event is still phrased by a template.
        """
        if self.waiting is None or self.announcer is None:
            return ""
        wanted = summary.strip().lower()

        def mine(event: dict[str, Any]) -> bool:
            if not wanted:
                return True
            return wanted in str(event.get("summary", "")).lower()

        freed = self.waiting.release(mine)
        if not freed:
            return ""
        held = freed[0]
        event = dict(held.event)
        event["_waited_because"] = held.explained()
        line = self._out_loud(event) or event.get("summary", "")
        if not line:
            return ""
        outcome = self.announcer.speak(
            str(line), source=f"{event.get('source', 'marvi')}:{event.get('kind', 'event')}"
        )
        logger.info(
            "said a held item because it was asked for: %r", str(line)[:100],
            extra={"marvi_played": bool(outcome.get("played"))},
        )
        return str(line) if outcome.get("played") else ""

    def _waited_for(
        self,
        moment: datetime,
        conversation_active: bool,
        present: bool,
        at_machine: bool | None,
        doing: str,
    ) -> list[dict[str, Any]]:
        """Events from the waiting room that may be spoken now.

        The policy decides, exactly as it did the first time -- this only asks
        it again against a world that has moved on. `_released` marks them so a
        second refusal does not put them straight back in the room.
        """
        if self.waiting is None:
            return []
        world = self.world(moment, conversation_active, present, at_machine, doing)

        def may_speak(event: dict[str, Any]) -> bool:
            # Held because no model would read it, and a model might now.
            # This is the whole "the rate limit has cleared, say it" case: the
            # item was kept, never summarised, and has been waiting for a
            # working model rather than for a better moment.
            payload = event.get("payload")
            # Deferred, not attempted. Walking into a known cooldown produces
            # the same refusal on every tick and teaches nothing; the item is
            # already safe in the waiting room and five minutes is nothing.
            if self.models_resting is not None and (resting := self.models_resting()) > 0:
                logger.info(
                    "not reading held items for another %.0fs; a model is cooling down",
                    resting,
                    extra={"marvi_resting_seconds": round(resting)},
                )
                return False

            unread = (
                self.read_late is not None
                and isinstance(payload, dict)
                and not str(payload.get("says") or "").strip()
                and bool(payload.get("body"))
            )
            if unread and (
                says := self.read_late(str(payload.get("subject", "")), str(payload["body"]))
            ):
                payload["says"] = says
                logger.info(
                    "read something that arrived while no model would answer: %r", says[:100]
                )
            verdict = evaluate(event, world, self.settings, wanted="speak")
            return SURFACES.index(verdict.surface) >= SURFACES.index("speak")

        freed = []
        for held in self.waiting.release(may_speak):
            event = dict(held.event)
            event["_released"] = True
            # Carried so `voicing` can explain the delay: six hours late is
            # alarming, "while you were out" is an assistant that waited.
            event["_waited_because"] = held.explained()
            freed.append(event)
        return freed

    def tick(
        self,
        now: datetime | None = None,
        conversation_active: bool = False,
        present: bool = True,
        at_machine: bool | None = None,
        doing: str = "",
    ) -> dict[str, Any]:
        moment = now or datetime.now(UTC)

        # Anything held back earlier, offered again first.
        #
        # Every rule that stops her speaking is a rule about *now* -- in a
        # call, out of the house, the middle of the night, a rate-limited
        # model -- and none of them is a reason to never say it. See
        # `pending`: the mailbox-deletion mail arrived at 03:10, was
        # downgraded for quiet hours, and was never mentioned again.
        pending = list(self._waited_for(moment, conversation_active, present, at_machine, doing))
        pending += self.journal.pending(limit=MAX_EVENTS_PER_TURN)
        if not pending:
            # The cheap, normal case: nothing happened, nothing to answer for.
            logger.debug("mind tick idle", extra={"marvi_pending": 0})
            return {"considered": 0, "decisions": [], "surfaced": []}

        base = self.world(moment, conversation_active, present, at_machine, doing)
        decisions: list[dict[str, Any]] = []
        surfaced: list[dict[str, Any]] = []
        logger.info(
            "mind tick started",
            extra={
                "marvi_pending": len(pending),
                "marvi_conversation_active": conversation_active,
                "marvi_present": present,
                "marvi_at_machine": at_machine,
                "marvi_doing": doing[:120],
                "marvi_tokens_today": base.tokens_today,
            },
        )

        for event in pending:
            started = time.perf_counter()
            world = replace(
                base,
                last_surfaced=self.journal.last_surfaced(event["source"], event["kind"]),
            )
            wanted = self._wanted_surface(event)
            verdict = evaluate(event, world, self.settings, wanted=wanted)
            # Nobody home to hear it, and a phone to send it to instead.
            textable = verdict.rule == "nobody-present" and self.messenger is not None
            # Worth saying, and not sayable yet. Held rather than dropped.
            # Held later instead, if the text does not go through.
            if (
                self.waiting is not None
                and SURFACES.index(wanted) >= SURFACES.index("speak")
                and SURFACES.index(verdict.surface) < SURFACES.index("speak")
                and not event.get("_released")
                and not textable
            ):
                self.waiting.hold(event, verdict.rule)
            # How much this is worth, before anything is paid to find out.
            #
            # The first stage of the Amygdala in PLAN.md: deterministic
            # salience ahead of any optional model judgement. Repetition is the
            # whole signal -- a sensor that has flipped forty times this hour is
            # not news the forty-first time -- and nothing here reads the
            # event's text, so wording cannot argue its way past it.
            worth = salience.assess(
                self.journal.seen_recently(
                    event["source"],
                    event["kind"],
                    moment - timedelta(seconds=salience.WINDOW_SECONDS),
                )
                - 1,
                urgent=SURFACES.index(wanted) >= SURFACES.index("speak"),
            )
            logger.info(
                "mind policy evaluated event",
                extra={
                    "marvi_event_id": event["id"],
                    "marvi_source": event["source"],
                    "marvi_kind": event["kind"],
                    "marvi_trusted": event["trusted"],
                    "marvi_rule": verdict.rule,
                    "marvi_salience": round(worth.score, 3),
                    "marvi_repeats": worth.repeats,
                    "marvi_surface_ceiling": verdict.surface,
                    "marvi_llm_eligible": bool(
                        self.deliberate is not None and verdict.allow and verdict.surface != "silent"
                    ),
                },
            )

            surface, detail, tokens, provider = verdict.surface, verdict.detail, 0, "deterministic"
            # `detail` is diagnostic text about the rule. What Marvi would
            # actually say is separate, and only deliberation can phrase it.
            # What she would say, rather than what the journal recorded.
            #
            # `event["summary"]` is written to be read later -- `room:
            # light_changed - light 80% (warm)` -- and an announcer reading
            # that aloud is a dashboard with a speaker bolted on. `voicing`
            # turns the ones it recognises into what a person would say, and
            # returns empty for the rest, so nothing is lost by not knowing.
            sentence = self._out_loud(event) or event["summary"]
            if (
                not worth.worth_a_model
                and verdict.surface != "silent"
                # The same exception as below: repetition is a good reason not
                # to spend a model call and a bad reason not to say hello. A
                # welcome is repetitive by nature -- it happens every time you
                # walk in -- which is exactly what this gate is built to damp.
                and not must_be_said(event)
            ):
                # Recorded, inspectable, and not thought about. The event still
                # reaches the journal and the activity feed; what it stops
                # buying is a model call to confirm what arithmetic already
                # said.
                surface, detail = _cap_to_activity(verdict.surface), worth.reason
            if (
                self.deliberate is not None
                and verdict.allow
                and worth.worth_a_model
                and _worth_thinking_about(verdict)
            ):
                # An LLM may only make a decision quieter, never louder: the
                # policy ceiling is not something a model gets to argue with.
                proposed, proposed_detail, tokens = self.deliberate(event, verdict)
                # ...and it may not silence the handful of things that are the
                # reason the feature exists. See `policy.MUST_BE_SAID`: a
                # welcome that is not said is not a quiet welcome, it is a
                # missing one, and one was silenced as "not worth interrupting".
                if proposed == "silent" and must_be_said(event):
                    logger.info(
                        "deliberation wanted silence on %s; saying it anyway",
                        f"{event.get('source')}:{event.get('kind')}",
                        extra={"marvi_event_id": event.get("id", "")},
                    )
                    proposed = verdict.surface
                    # And its words go with its verdict.
                    #
                    # `proposed_detail` is the model's *reason for wanting
                    # silence*, not a line to deliver. Keeping it and then
                    # speaking anyway is how this reached the room:
                    #
                    #     00:19:01  FC 26 started  speak  "not worth interrupting"
                    #
                    # Marvi read the veto out loud. Cleared, so the sentence
                    # falls back to the template `voicing` already wrote.
                    proposed_detail = ""
                if SURFACES.index(proposed) <= SURFACES.index(verdict.surface):
                    surface = proposed
                    # Only overwrite the reason when there is one. An empty
                    # detail means "no opinion", not "no reason".
                    detail = proposed_detail or verdict.detail
                    # A model may choose how loud, never what is said, when the
                    # event came from outside.
                    #
                    # This is the whole reason an email can now be spoken at
                    # all. The template in `voicing` fills fields, so the worst
                    # a hostile subject line achieves is Marvi reading out
                    # something odd. A model that has *read* that subject line
                    # and is writing the sentence is a different proposition
                    # entirely -- there the text is an instruction, and the
                    # thing it instructs is the sentence Marvi says out loud.
                    # Deliberation still runs and can still quieten this event;
                    # it just does not get to put words in her mouth.
                    if proposed_detail and event["trusted"]:
                        sentence = proposed_detail
                resolved_provider = str(getattr(self.deliberate, "last_provider", "") or "llm")
                resolved_model = str(getattr(self.deliberate, "last_model", "") or "")
                provider = (
                    f"{resolved_provider}/{resolved_model}" if resolved_model else resolved_provider
                )

            if surface == "remember" and self.memory is not None:
                # Rendered, not `str(dict)`. This is where two memories in the
                # real store came to have a Python dict repr for a body:
                #
                #     subject: User shared a link
                #     body:    {'id': 'User shared a link'}
                #
                # `initiative.run_ingest` journals `{"id": subject}` as the
                # payload, `str()` took it without complaint, and the store
                # kept a row that no search will ever match usefully.
                body = _readable(event["payload"])[:2000]
                if event["trusted"]:
                    self.memory.remember(event["summary"], body, kind="episodic")
                else:
                    # Untrusted in the journal stays untrusted in memory.
                    self.memory.remember_external(
                        event["summary"], body, source=event["source"]
                    )

            # Deciding is over; saying it is a different cost.
            #
            # `latency` used to span the whole loop body, so it included the
            # announcer playing the audio -- and reported 142 seconds against
            # "FC 26 started" on a page whose column reads "what it cost to
            # decide". The deliberation had taken 1.5 seconds; the other 141
            # were a text-to-speech run competing with the game she was
            # standing aside for, which is a real problem and a completely
            # different one.
            decided_in = (time.perf_counter() - started) * 1000
            said_started = time.perf_counter()

            spoken = ""
            # Never load the voice for the first time while a game has the
            # machine. Warming happens at startup, so this is the case where
            # that failed or the model was evicted -- and a 140-second cold
            # load is the one thing guaranteed to ruin what she is standing
            # aside for. Held instead, and said when the game is over.
            if (
                surface == "speak"
                and self.announcer is not None
                and getattr(self.announcer, "cold", False)
                and self.busy_with()
                and self.waiting is not None
            ):
                logger.info(
                    "not loading the voice while %s has the machine; holding it "
                    "and warming in the background",
                    self.busy_with(),
                )
                self.waiting.hold(event, "resources")
                surface = "island"
                # Warmed anyway, on a thread, so this is a delay and not a
                # silence. The announcer is the one thing that must still work
                # during a game -- it is how you learn she noticed the game at
                # all, and it is where anything that matters while you are
                # playing has to come out. It is 438MB on the CPU: light
                # enough to hold, and only ever cold because a restart landed
                # mid-match. Held here, said on the next tick.
                threading.Thread(
                    target=self.announcer.warm, name="marvi-warm-voice", daemon=True
                ).start()
            if surface == "speak" and self.announcer is not None:
                outcome = self.announcer.speak(
                    sentence,
                    source=f"{event.get('source', 'marvi')}:{event.get('kind', 'event')}",
                )
                if outcome.get("played"):
                    spoken = sentence
                else:
                    # Losing a voice is not losing the decision; drop to the
                    # Island so the user still sees it.
                    surface = "island"
                    detail = f"{detail} (speech unavailable)".strip()

            texted = ""
            if textable:
                # `island` is what "nobody-present" downgrades speech to; a
                # deliberation that made it quieter than that stays quieter,
                # and is held for later as it always was.
                if surface == "island" and self.messenger(sentence, event):
                    texted = sentence
                elif self.waiting is not None and not event.get("_released"):
                    self.waiting.hold(event, verdict.rule)

            latency = decided_in
            said_in = (time.perf_counter() - said_started) * 1000
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
                else ("texted: " + texted) if texted
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
                    "marvi_said_ms": round(said_in, 2),
                },
            )

            record = {
                "id": decision_id,
                "event": event["summary"],
                "surface": surface,
                "rule": verdict.rule,
                "detail": detail,
                "latency_ms": round(latency, 2),
                # Kept apart so a slow voice never reads as slow thinking.
                "said_ms": round(said_in, 2),
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
