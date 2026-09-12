"""The proactivity contract, as code.

`REAL-AGENCY.md` says a proactive turn is allowed only when five conditions
hold. This module is those conditions, in order, each as a named rule — so the
answer to "why did Marvi speak?" and the equally important "why did Marvi stay
quiet?" is always a rule name rather than a shrug.

Silence is the default and costs nothing. The checks run cheapest-first and
stop at the first refusal, so an ordinary tick that decides nothing does almost
no work.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any


def _int_env(name: str, fallback: int, low: int, high: int) -> int:
    """Read an integer setting, clamped. A typo in a config file should not be
    able to switch proactivity off by accident, or leave it uncapped."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return fallback
    try:
        return max(low, min(int(raw), high))
    except ValueError:
        return fallback


# The least intrusive surface that is still useful, most quiet first.
SURFACES = ("silent", "remember", "activity", "island", "speak", "propose")

#: Events a model may reword but may not silence.
#:
#: Deliberation exists to stop Marvi narrating every light change, and it is
#: right about almost everything. It is not right about these, because these
#: are the moments the feature exists for -- and it silenced one:
#:
#:     23:11:34  Welcome. Shereef isn't here right now.   silent
#:               not worth interrupting                   openrouter 1583ms
#:
#: A welcome that is not said is not a quiet welcome, it is a missing one. The
#: ceiling table is a person's decision about what matters; a model's job here
#: is phrasing and the marginal calls, not vetoing the decision itself.
MUST_BE_SAID: frozenset[str] = frozenset({
    "room:room_welcome",
    # Somebody walked in. It was capped at `activity` by falling through to the
    # default, so 147 arrivals were recorded and none was ever mentioned --
    # while `room_welcome`, which is the one that speaks, fired 9 times because
    # of a separate one-hour gate. Between them, walking into your own room
    # produced silence.
    "room:room_entry",
    "room:visitor_report",
    "room:visitor_photos",
    "room:room_presence_unverified",
    "room:alarm_started",
    "room:alarm_requested",
    "schedule:reminder",
    "schedule:insistent_reminder",
    "machine:disk_critical",
    "system:feed_quiet",
    # Going quiet without saying why is the failure this whole path exists to
    # stop: a rate-limited model, an unreachable Gateway and a recogniser that
    # heard nothing all look identical from outside -- a pause, then nothing.
    "system:model_resting",
    "machine:battery_critical",
    "focus:heavy_app_started",
    "focus:heavy_app_ended",
})


def must_be_said(event: dict[str, Any]) -> bool:
    """Whether deliberation is allowed to silence this one."""
    return f"{event.get('source')}:{event.get('kind')}" in MUST_BE_SAID


#: No cooldown. It was fifteen minutes, and it was the wrong instrument.
#:
#: A blanket timer cannot tell the difference between the second announcement
#: of the same nothing and the one thing that mattered all afternoon -- it just
#: silences whatever comes second. Everything it was protecting against is
#: judged better elsewhere: repetition by `salience`, worth by the
#: deliberator, presence and hour by their own gates.
#:
#: Still a setting, and still honoured when set. Somebody who wants a floor
#: between interruptions can have one; it is simply not the default any more,
#: because "she never says anything twice in a quarter of an hour" was
#: producing an assistant who never said anything.
DEFAULT_COOLDOWN_SECONDS = 0
# Denominated in tokens, not money. Every provider reports tokens in the same
# way; a plan reports no spend at all, and a local model has no price. A budget
# in dollars would silently stop guarding on exactly the providers that need it.
DEFAULT_DAILY_TOKEN_BUDGET = 200_000
DEFAULT_QUIET_START = 23
DEFAULT_QUIET_END = 8

# How loud an event is allowed to get. Anything absent is Activity at most:
# an unknown event type should never be the thing that interrupts someone.
SURFACE_CEILING: dict[str, str] = {
    # Retained for journal compatibility with already-recorded alarm events.
    "room:alarm_started": "speak",
    "room:alarm_requested": "speak",
    "room:room_presence_unverified": "speak",
    "room:room_welcome": "speak",
    "room:visitor_report": "speak",
    "room:mode_changed": "activity",
    "room:light_changed": "activity",
    # Keyed on what the ingest actually writes.
    #
    # `run_ingest` journals `source=f"accounts:{toolkit}"` and `kind=toolkit`,
    # so the key the policy builds is `accounts:gmail:gmail` -- and the two
    # entries that used to live here, `accounts:email` and `accounts:calendar`,
    # could never match anything. The intent ("email and calendar are worth a
    # glance") has been dead configuration for as long as accounts have been
    # ingested this way, and both fell through to the default instead.
    # Mail, appointments and mentions are the three things worth being told
    # about out loud; `voicing` has a template for each. Everything below is
    # still filtered by salience, repetition, quiet hours and the budget before
    # any of it is heard.
    "accounts:gmail:gmail": "speak",
    "accounts:googlecalendar:googlecalendar": "speak",
    "accounts:github:github": "speak",
    "accounts:slack:slack": "island",
    # The machine about itself. First-party, so there is no stranger's text in
    # any of it -- what is left is only the question of whether it is worth
    # interrupting for, and a disk about to fail a write is.
    # Stepping off the GPU for a game. Said out loud on purpose: doing it
    # silently is the same as not doing it, from where the person is sitting.
    "focus:heavy_app_started": "speak",
    "focus:heavy_app_ended": "speak",
    # A source that has gone quiet. Worth saying because the failure shape is
    # silence: nothing turns red, and the last reading stands there looking
    # current. Thirteen days of "Phone: HOME" from a stale geofence is what
    # not saying it costs.
    "system:feed_quiet": "speak",
    # A model resting. Only reported when it leaves nothing else to think
    # with, so this is Marvi saying she is about to be slower or quieter --
    # which beats being thought broken. See `providers.client.stand_down`.
    "system:model_resting": "speak",
    "machine:disk_critical": "speak",
    "machine:disk_low": "island",
    "machine:battery_critical": "speak",
    "machine:battery_low": "island",
    "machine:power_unplugged": "activity",
    "machine:power_plugged": "activity",
    "machine:memory_tight": "island",
    "machine:network_lost": "speak",
    "machine:network_back": "activity",
    "accounts:notion:notion": "activity",
    # The older shape, kept so events already in the journal still resolve.
    "accounts:email": "island",
    "accounts:calendar": "island",
    # The noisiest source on this machine by two orders of magnitude: 11,438 of
    # 12,123 events, 94% of everything the mind has ever seen. It had no entry
    # here, so it defaulted to `activity` -- which is *allowed and not silent*,
    # which means every one of them bought an LLM call. That is where 95,186
    # tokens went, and the budget they exhausted then silenced 22 of the 23
    # real calendar events behind them.
    #
    # A sleep-state transition is a thing to record, not a thing to think
    # about. `silent` still journals it; it just stops paying a model to agree.
    "room:vision_sleep_state": "silent",
    "room:vision_visitor_seen": "activity",
    "room:presence_detected": "silent",
    "room:presence_cleared": "silent",
    # Somebody walked in. This was "activity", so 147 arrivals were recorded
    # and none was ever mentioned -- while `room_welcome`, the one that speaks,
    # fired 9 times because of a separate one-hour gate. Between them, walking
    # into your own room produced silence.
    "room:room_entry": "speak",
    "room:device_offline": "activity",
    "schedule:reminder": "speak",
    "schedule:insistent_reminder": "speak",
    "vision:visitor_report": "speak",
    "vision:owner_seen": "activity",
    "room:vision_gesture": "activity",
    "memory:reflection": "remember",
    # Something she worked out that nobody told her.
    #
    # Unlisted until now, which meant the default -- `activity`, a line in a
    # feed. Twenty conclusions were drawn and every one of them stopped there,
    # including the one that would have ended a whole argument:
    #
    #     Shereef prefers "good morning" over "good night" because his sleep
    #     schedule involves going to sleep in the morning
    #
    # concluded at 01:37, capped at a feed entry, and the next conversation
    # was spent correcting her about it. An assistant that notices things and
    # cannot mention them is a notebook.
    #
    # `speak` is a ceiling, not an instruction: salience, the cooldown, quiet
    # hours, presence and the deliberator all still stand between a conclusion
    # and a spoken word, and dreaming only runs twice a day.
    "memory:conclusion": "speak",
    # Something she wants to know and cannot look up.
    #
    # `curiosity.may_ask` has always been able to name one thing worth asking
    # and nothing ever asked it outside a turn, so she noticed while being
    # spoken to and never went looking. A question is the most intrusive thing
    # she can offer unprompted -- it wants an answer -- which is why the job
    # behind it is the slowest on the scheduler and why this is still only a
    # ceiling: presence, the hour and the deliberator all still apply.
    "curiosity:question": "speak",
    # Someone who is not the owner messaged the Telegram bot. Worth a glance,
    # never a word: the name in it was typed by a stranger.
    "telegram:stranger": "island",
}


#: How loud an arrival may be, by who the room thinks it was.
#:
#: One ceiling for every `room_entry` made the owner shifting in his chair as
#: loud as a stranger: "Owner entered the room" was spoken on 11 September as
#: "there is someone in the room while you are out". The owner's real arrival
#: already has a voice -- `room_welcome`, gated on the room having been empty --
#: so his re-detections are a record. A guess stays glanceable; only the
#: phone being somewhere else is worth saying out loud.
ENTRY_CEILING: dict[str, str] = {
    "owner": "activity",
    # A friend the camera named. Their welcome speaks through `room_welcome`.
    "known_person": "island",
    "guest": "island",
    "unidentified": "island",
    "unknown_visitor": "speak",
}


@dataclass(frozen=True)
class Verdict:
    allow: bool
    surface: str
    rule: str
    detail: str = ""


@dataclass
class InitiativeSettings:
    """Everything the user can turn down. Defaults are deliberately quiet."""

    paused: bool = False
    #: Whether there are quiet hours at all.
    #:
    #: Turning them off was possible only by accident -- setting start and end
    #: to the same hour makes the window empty -- which is not a setting, it is
    #: a trick. Somebody who works nights, or who simply wants to be told
    #: things at two in the morning, should be able to say so.
    quiet_enabled: bool = True
    #: Whether the journal drops a repeated event for six hours.
    #:
    #: On is right nearly always -- a mailbox re-reporting the same message
    #: every poll is one event, not forty. It is wrong exactly when a repeat
    #: is the news: the same game opened twice, the same reminder run twice.
    #: Those are fixed where they happen; this is for the ones nobody has hit
    #: yet, because the failure mode is silence and silence is not findable.
    dedupe_events: bool = True
    quiet_start: int = DEFAULT_QUIET_START
    quiet_end: int = DEFAULT_QUIET_END
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
    daily_token_budget: int = DEFAULT_DAILY_TOKEN_BUDGET
    #: Whether she speaks into a room with nobody in it.
    #:
    #: Named for the room rather than for the person: the check is presence in
    #: *this* room, so "away" here means the mmWave and the camera agree
    #: nobody is there, not that the user is out of the house. Off, because
    #: talking to an empty room is the clearest waste there is -- and because
    #: the announcement is not lost when it is held. See `pending`.
    speak_when_away: bool = False
    surface_ceiling: dict[str, str] = field(default_factory=lambda: dict(SURFACE_CEILING))

    @classmethod
    def from_env(cls) -> InitiativeSettings:
        """Every knob here changes how often Marvi speaks, so every one of them
        resolves from the environment and is editable from the control center.
        A quiet-hours window buried in a constant is a setting the user cannot
        reach."""
        return cls(
            paused=os.environ.get("MARVI_INITIATIVE", "").strip().lower()
            in ("0", "off", "false", "paused"),
            quiet_enabled=os.environ.get("MARVI_QUIET_ENABLED", "1").strip().lower()
            not in ("0", "off", "false", "no"),
            dedupe_events=os.environ.get("MARVI_DEDUPE_EVENTS", "1").strip().lower()
            not in ("0", "off", "false", "no"),
            quiet_start=_int_env("MARVI_QUIET_START", DEFAULT_QUIET_START, 0, 23),
            quiet_end=_int_env("MARVI_QUIET_END", DEFAULT_QUIET_END, 0, 23),
            cooldown_seconds=_int_env(
                "MARVI_SURFACE_COOLDOWN", DEFAULT_COOLDOWN_SECONDS, 0, 24 * 3600
            ),
            daily_token_budget=_int_env(
                "MARVI_DAILY_TOKEN_BUDGET", DEFAULT_DAILY_TOKEN_BUDGET, 0, 100_000_000
            ),
            speak_when_away=os.environ.get("MARVI_SPEAK_WHEN_AWAY", "").strip().lower()
            in ("1", "on", "true", "yes"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "paused": self.paused,
            "quiet_enabled": self.quiet_enabled,
            "dedupe_events": self.dedupe_events,
            "quiet_start": self.quiet_start,
            "quiet_end": self.quiet_end,
            "cooldown_seconds": self.cooldown_seconds,
            "daily_token_budget": self.daily_token_budget,
            "speak_when_away": self.speak_when_away,
        }


@dataclass
class WorldState:
    """What the policy needs to know about right now."""

    now: datetime
    conversation_active: bool = False
    present: bool = True
    tokens_today: int = 0
    last_surfaced: datetime | None = None
    #: Whether the desktop says somebody is at the machine, from ActivityWatch.
    #: None when it is not installed or did not answer.
    #:
    #: `present` comes from the room's presence sensor and *fails open* -- the
    #: mind defaults to True and only lowers it if the room answers, so with the
    #: room offline Marvi assumes somebody is there and may speak to an empty
    #: room. The desktop knows better and cheaper: a machine that is not idle
    #: has a person in front of it.
    at_machine: bool | None = None
    #: What they appear to be doing -- "in Code, browsing github.com". Not used
    #: by any rule; carried so the deliberation and the decision record can say
    #: what the moment looked like.
    doing: str = ""
    #: The room is in sleep mode -- set by the person, not guessed by a sensor.
    #:
    #: The one signal this policy never read. Quiet hours are a clock, and the
    #: owner sleeps in the morning: sleep mode went on at 08:20 and "Unidentified
    #: entered the room" was spoken at 08:32, because quiet hours had already
    #: ended and nothing else asked whether anybody was asleep.
    asleep: bool = False


def _quiet_now(settings: InitiativeSettings, now: datetime) -> bool:
    if not settings.quiet_enabled:
        return False
    start, end = settings.quiet_start, settings.quiet_end
    hour = now.astimezone().hour
    # Quiet hours normally wrap midnight.
    return hour >= start or hour < end if start > end else start <= hour < end


#: What each ceiling means, for the person reading the Decisions list.
CEILING_SAID: dict[str, str] = {
    "speak": "worth saying out loud",
    "island": "worth showing, not saying",
    "activity": "worth recording only",
    "remember": "kept in memory",
    "silent": "not worth recording",
}


def _cap(surface: str, ceiling: str) -> str:
    """Never louder than the ceiling for this kind of event."""
    return surface if SURFACES.index(surface) <= SURFACES.index(ceiling) else ceiling


def evaluate(
    event: dict[str, Any],
    world: WorldState,
    settings: InitiativeSettings | None = None,
    wanted: str = "island",
) -> Verdict:
    """Decide the loudest surface this event is allowed to reach."""
    rules = settings or InitiativeSettings()

    # 1. The user has the final say, and it is checked before anything else.
    if rules.paused:
        return Verdict(False, "silent", "initiative-paused", "initiative is switched off")

    # 2. Untrusted content may inform, never command.
    #
    #    The cap used to be `island`, one rung tighter than that sentence
    #    argues for: `propose` is where an event becomes the reason to *do*
    #    something, and that is the surface worth denying to text a stranger
    #    wrote. `speak` only reads it out. Capping at `island` meant an email
    #    could never be mentioned at all -- which, with `mind` refusing to let
    #    a model phrase an untrusted event, is a restriction that bought no
    #    safety and cost the whole feature.
    ceiling = rules.surface_ceiling.get(f"{event.get('source')}:{event.get('kind')}", "activity")
    if f"{event.get('source')}:{event.get('kind')}" == "room:room_entry":
        payload = event.get("payload")
        who = payload.get("classification") if isinstance(payload, dict) else None
        ceiling = _cap(ENTRY_CEILING.get(str(who), "island"), ceiling)
    if not event.get("trusted", False) and SURFACES.index(ceiling) > SURFACES.index("speak"):
        ceiling = "speak"

    # 2b. She only says out loud what she actually read.
    #
    #     Shereef, mail from LinkedIn Job Alerts - Cybersecurity Engineer at ...
    #     Shereef, mail from Cloudflare - See Fei-Fei Li live at Connect.
    #
    #     Icemail will delete your three Google mailboxes today unless you pay.
    #
    # The first two are notifications and the third is an assistant, and the
    # difference is entirely whether `gatekeeping` read the body and worked out
    # what it meant. That gate *fails open* on purpose -- a model being rate
    # limited must never mean a week of missing correspondence -- so on a bad
    # afternoon everything arrives unjudged. Unjudged is fine to show and wrong
    # to announce: it is precisely the ten-envelopes-in-a-row case.
    #
    # So the raised ceiling is conditional on there being something to say.
    # Nothing is lost when it fails: the mail still reaches the Island and the
    # activity feed, exactly as it did before any of this.
    unread = False
    if str(event.get("source", "")).startswith("accounts:"):
        payload = event.get("payload")
        read_it = isinstance(payload, dict) and str(payload.get("says") or "").strip()
        if not read_it and SURFACES.index(ceiling) > SURFACES.index("island"):
            ceiling, unread = "island", True

    surface = _cap(wanted, ceiling)

    # 3. Budget: a day has a thinking limit, and exceeding it is not an
    #    emergency, it is silence.
    if world.tokens_today >= rules.daily_token_budget:
        return Verdict(
            False, "silent", "daily-budget", f"{world.tokens_today} tokens used today"
        )

    # 3b. Presence, corrected by the desktop.
    #
    # The room's sensor is the better signal when it works and the mind
    # defaults to "present" when it does not -- which is the wrong way round
    # for a rule about whether to speak aloud. ActivityWatch answers a narrower
    # question ("is somebody using this machine") reliably, so it is allowed to
    # *add* presence, never to remove it: somebody can be in the room without
    # touching the keyboard, and idle at the desk is not absent from the house.
    if world.at_machine and not world.present:
        world = replace(world, present=True)

    # 4. Never talk over a live conversation. The foreground owns the voice.
    if world.conversation_active and SURFACES.index(surface) >= SURFACES.index("island"):
        return Verdict(
            True, _cap("activity", ceiling), "conversation-active", "logged instead of interrupting"
        )

    # 5. Cooldown, so a chatty source cannot become a stream of interruptions.
    if world.last_surfaced is not None and SURFACES.index(surface) >= SURFACES.index("island"):
        quiet_for = (world.now - world.last_surfaced).total_seconds()
        if quiet_for < rules.cooldown_seconds:
            return Verdict(
                True, _cap("activity", ceiling), "cooldown", f"last surfaced {quiet_for:.0f}s ago"
            )

    # 6. One opt-in exemption, and only for a schedule the user marked as
    #    insistent. Quiet hours downgrade speech to a glance, which is right for
    #    "you have email" and useless for an alarm set for 07:00 — an alarm that
    #    appears silently on a screen is not an alarm.
    #
    #    Per-schedule rather than per-source: the first version exempted every
    #    schedule, which would have let "check my mail hourly" fire out loud at
    #    3am. Asking for an hourly check is not asking to be woken by it.
    #
    #    Deliberately narrow. Everything above still applies: it cannot talk
    #    over a live conversation, it cannot escape the cooldown, and it is still
    #    capped by its ceiling.
    insistent = event.get("source") == "schedule" and (
        event.get("kind") == "insistent_reminder"
        or bool((event.get("payload") or {}).get("insist"))
    )

    # 6b. Sleep mode silences her, whatever the clock says.
    #
    #     Stronger than quiet hours and checked first, because it is the person
    #     saying so rather than a time window guessing: someone who switched the
    #     room to sleep does not want to hear that they turned over. Only an
    #     insistent reminder gets through -- an alarm that cannot wake you is
    #     not an alarm, and that is the one thing sleep mode is not asked to
    #     stop. `pending` holds the rest and offers it once the room wakes.
    if not insistent and world.asleep and SURFACES.index(surface) >= SURFACES.index("speak"):
        return Verdict(True, _cap("island", ceiling), "asleep", "held while the room sleeps")

    # 7. Quiet hours downgrade speech to something glanceable.
    if (
        not insistent
        and _quiet_now(rules, world.now)
        and SURFACES.index(surface) >= SURFACES.index("speak")
    ):
        return Verdict(True, _cap("island", ceiling), "quiet-hours", "downgraded from speech")

    # 8. Speaking to an empty room is noise, not initiative.
    speaking = SURFACES.index(surface) >= SURFACES.index("speak")
    if speaking and not insistent and not world.present and not rules.speak_when_away:
        return Verdict(True, _cap("island", ceiling), "nobody-present", "downgraded from speech")

    if unread:
        # Named rather than lumped in with "allowed", so `pending` can hold it
        # and try again once a model is available. A rate limit is the most
        # temporary reason of all to not say something.
        return Verdict(True, surface, "unread", "no summary yet; a model was unavailable")
    # In words, because this reaches a page a person reads.
    #
    # It said "ceiling speak" and "ceiling silent", which is the name of an
    # internal table and a variable, shown to somebody who has never seen
    # either. The Decisions list is meant to answer "why did she not say
    # anything", and "ceiling silent" does not answer it.
    return Verdict(True, surface, "allowed", CEILING_SAID.get(ceiling, f"can {ceiling}"))


def day_start(now: datetime) -> datetime:
    return now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def next_quiet_end(settings: InitiativeSettings, now: datetime) -> datetime:
    local = now.astimezone()
    end = local.replace(hour=settings.quiet_end, minute=0, second=0, microsecond=0)
    if end <= local:
        end += timedelta(days=1)
    return end.astimezone(UTC)
