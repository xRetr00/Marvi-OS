"""How much a world event is worth, decided without a model.

The first stage of the Amygdala described in `PLAN.md`: *"compute deterministic
safety/urgency signals before any optional model judgement"*. This is that
stage, and it exists because the alternative was measured.

Over 946 real decisions the Mind spent **911,280 tokens**, and 97.4% of those
calls ended in `silent`. Two event kinds accounted for 90.1% of every token
ever spent:

    room:vision_sleep_state    11,447 of 12,135 events   94.3% of all events
    room:vision_visitor_seen

Neither is news. A sleep-state sensor that flips forty-seven times in an
evening is reporting one fact badly, and a model was paid roughly nine hundred
tokens each time to read it and agree it was not worth mentioning. Four days
running, that exhausted the daily budget — and the exhausted budget then
silenced 22 of the 23 real calendar events queued behind it.

## The rule

Repetition is the signal. A thing that just happened forty times is not news
the forty-first time, and deciding that needs arithmetic rather than judgement:

    score = 1 / (1 + repeats within the window)

The first occurrence scores 1.0, the second 0.5, the tenth 0.09. Below
`WORTH_A_MODEL` the event still reaches the journal and the activity feed — it
is recorded, it is inspectable, it is simply not *thought about*.

## What repetition must never suppress

An alarm that fires every morning is repetitive and it is the whole point.
Anything the policy is willing to speak has a floor: `URGENT_FLOOR` keeps it
above the threshold no matter how often it recurs. Novelty is a reason to think
harder, never a licence to ignore something that matters.

`PLAN.md` also asks that "untrusted instructions cannot raise authority through
emotional wording". Nothing here reads the event's *text* at all — the score
comes from how often a `(source, kind)` has fired, which is not something the
content can argue with.
"""

from __future__ import annotations

from dataclasses import dataclass

#: How far back to count repeats.
#:
#: An hour, because that is the span over which a flapping sensor is obviously
#: one event and two unrelated emails obviously are not. Shorter and a burst
#: spread over twenty minutes reads as novel each time; longer and a genuinely
#: periodic thing — a daily standup reminder — is suppressed for being daily.
WINDOW_SECONDS = 60 * 60

#: Below this, an event is recorded but not reasoned about.
#:
#: A third of full salience: the first two occurrences in the window still get
#: thought about, the third does not. Two is enough to notice a change of state
#: and see it confirmed; the third is the sensor talking to itself.
WORTH_A_MODEL = 0.34

#: What repetition can never take away from something the policy would speak.
#: An alarm that goes off every morning is repetitive by design.
URGENT_FLOOR = 1.0


@dataclass(frozen=True)
class Salience:
    """What this event is worth, and why. Never derived from its text."""

    score: float
    repeats: int
    reason: str

    @property
    def worth_a_model(self) -> bool:
        return self.score >= WORTH_A_MODEL

    @property
    def novel(self) -> bool:
        return self.repeats == 0


def assess(repeats: int, *, urgent: bool = False) -> Salience:
    """Score an event from how often its kind has fired recently.

    `repeats` is the count of events with the same source and kind inside
    `WINDOW_SECONDS`, not counting this one. `urgent` is for anything the
    policy is willing to speak, which repetition may not suppress.
    """
    count = max(0, int(repeats))
    if urgent:
        return Salience(URGENT_FLOOR, count, "urgent kinds do not decay")
    score = 1.0 / (1.0 + count)
    if count == 0:
        return Salience(score, count, "first of its kind this hour")
    if score >= WORTH_A_MODEL:
        return Salience(score, count, f"seen {count} time(s) this hour")
    return Salience(score, count, f"seen {count} times this hour; recorded, not reasoned about")
