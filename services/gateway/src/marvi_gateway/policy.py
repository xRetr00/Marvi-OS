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
from dataclasses import dataclass, field
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

DEFAULT_COOLDOWN_SECONDS = 15 * 60
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
    "accounts:email": "island",
    "accounts:calendar": "island",
    "schedule:reminder": "speak",
    "schedule:insistent_reminder": "speak",
    "vision:visitor_report": "speak",
    "vision:owner_seen": "activity",
    "room:vision_gesture": "activity",
    "memory:reflection": "remember",
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
    quiet_start: int = DEFAULT_QUIET_START
    quiet_end: int = DEFAULT_QUIET_END
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
    daily_token_budget: int = DEFAULT_DAILY_TOKEN_BUDGET
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


def _quiet_now(settings: InitiativeSettings, now: datetime) -> bool:
    start, end = settings.quiet_start, settings.quiet_end
    hour = now.astimezone().hour
    # Quiet hours normally wrap midnight.
    return hour >= start or hour < end if start > end else start <= hour < end


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

    # 2. Untrusted content may inform, never command. It can be remembered and
    #    shown, but it can never be the reason Marvi proposes an action.
    ceiling = rules.surface_ceiling.get(f"{event.get('source')}:{event.get('kind')}", "activity")
    if not event.get("trusted", False) and SURFACES.index(ceiling) > SURFACES.index("island"):
        ceiling = "island"

    surface = _cap(wanted, ceiling)

    # 3. Budget: a day has a thinking limit, and exceeding it is not an
    #    emergency, it is silence.
    if world.tokens_today >= rules.daily_token_budget:
        return Verdict(
            False, "silent", "daily-budget", f"{world.tokens_today} tokens used today"
        )

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

    return Verdict(True, surface, "allowed", f"ceiling {ceiling}")


def day_start(now: datetime) -> datetime:
    return now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def next_quiet_end(settings: InitiativeSettings, now: datetime) -> datetime:
    local = now.astimezone()
    end = local.replace(hour=settings.quiet_end, minute=0, second=0, microsecond=0)
    if end <= local:
        end += timedelta(days=1)
    return end.astimezone(UTC)
