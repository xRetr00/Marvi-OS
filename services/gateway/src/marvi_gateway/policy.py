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

# The least intrusive surface that is still useful, most quiet first.
SURFACES = ("silent", "remember", "activity", "island", "speak", "propose")

DEFAULT_COOLDOWN_SECONDS = 15 * 60
DEFAULT_DAILY_BUDGET = 0.50
DEFAULT_QUIET_START = 23
DEFAULT_QUIET_END = 8

# How loud an event is allowed to get. Anything absent is Activity at most:
# an unknown event type should never be the thing that interrupts someone.
SURFACE_CEILING: dict[str, str] = {
    "room:alarm_started": "speak",
    "room:room_presence_unverified": "speak",
    "room:mode_changed": "activity",
    "room:light_changed": "activity",
    "accounts:email": "island",
    "accounts:calendar": "island",
    "schedule:reminder": "speak",
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
    daily_budget: float = DEFAULT_DAILY_BUDGET
    speak_when_away: bool = False
    surface_ceiling: dict[str, str] = field(default_factory=lambda: dict(SURFACE_CEILING))

    @classmethod
    def from_env(cls) -> InitiativeSettings:
        return cls(
            paused=os.environ.get("MARVI_INITIATIVE", "").strip().lower()
            in ("0", "off", "false", "paused"),
        )


@dataclass
class WorldState:
    """What the policy needs to know about right now."""

    now: datetime
    conversation_active: bool = False
    present: bool = True
    spent_today: float = 0.0
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

    # 3. Budget: a day has a spending limit, and exceeding it is not an
    #    emergency, it is silence.
    if world.spent_today >= rules.daily_budget:
        return Verdict(False, "silent", "daily-budget", f"spent {world.spent_today:.2f} today")

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

    # 6. Quiet hours downgrade speech to something glanceable.
    if _quiet_now(rules, world.now) and SURFACES.index(surface) >= SURFACES.index("speak"):
        return Verdict(True, _cap("island", ceiling), "quiet-hours", "downgraded from speech")

    # 7. Speaking to an empty room is noise, not initiative.
    speaking = SURFACES.index(surface) >= SURFACES.index("speak")
    if speaking and not world.present and not rules.speak_when_away:
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
