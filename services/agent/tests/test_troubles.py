"""Whether Marvi says what went wrong, and what she must never say.

Her failures were legible only in a log file. A rate-limited model, an
unreachable Gateway and a recogniser that heard nothing all looked the same
from outside: a pause, then nothing. `providers.log` had the exact reason
thirty-eight times in one afternoon and she mentioned none of them.
"""

from __future__ import annotations

import pytest

from marvi_agent.troubles import TROUBLES, Narrator


def test_a_rate_limited_provider_is_explained() -> None:
    said = Narrator().speak_about(
        RuntimeError("provider openrouter cooling down 300s: rate limited or window exhausted")
    )
    assert "rate limiting" in said
    # And what it means for the person waiting, not just what happened.
    assert "few minutes" in said


def test_an_unrecognised_fault_is_not_narrated() -> None:
    """Silence beats "something went wrong".

    A narrator that speaks on every unknown error is noise that teaches the
    person to ignore it, and says nothing they can act on.
    """
    assert Narrator().speak_about(RuntimeError("Kqp7 assertion at frame 91")) == ""


def test_the_same_trouble_is_not_repeated() -> None:
    # A model cooling down for five minutes fails every turn in that window.
    # Hearing the same sentence six times is worse than hearing it once.
    narrator = Narrator()
    fault = RuntimeError("429 rate limit")
    assert narrator.speak_about(fault, now=0.0)
    assert narrator.speak_about(fault, now=10.0) == ""
    assert narrator.speak_about(fault, now=1000.0), "it never says it again"


def test_a_different_trouble_is_still_worth_saying() -> None:
    narrator = Narrator()
    assert narrator.speak_about(RuntimeError("429 rate limit"), now=0.0)
    assert narrator.speak_about(RuntimeError("connection refused"), now=1.0)


def test_nothing_from_the_error_is_ever_spoken() -> None:
    """The line is written in the module; the fault is only ever read.

    Provider errors carry request URLs and auth headers. An assistant that
    reads its exceptions aloud reads an API key aloud -- to whoever is in the
    room, and into the transcript that goes to a model.
    """
    secret = "sk-or-v1-9f3c8a2e7b1d4056"
    said = Narrator().speak_about(
        RuntimeError(f"429 rate limit from https://openrouter.ai/api?key={secret}")
    )

    assert said, "this fault should still be explained"
    assert secret not in said
    assert "openrouter.ai" not in said
    assert said in {trouble.line for trouble in TROUBLES}


def test_an_error_that_cannot_be_rendered_is_survivable() -> None:
    # A __str__ that raises must not take down the turn it is reporting on.
    class Awkward:
        def __str__(self) -> str:
            raise ValueError("no")

    assert Narrator().speak_about(Awkward()) == ""


@pytest.mark.parametrize("trouble", TROUBLES, ids=lambda t: t.pattern.pattern[:20])
def test_every_line_says_something_a_person_can_act_on(trouble) -> None:
    # Short enough to interrupt with, and a whole sentence rather than a
    # fragment of a stack trace.
    assert 40 < len(trouble.line) < 200
    assert trouble.line[0].isupper() and trouble.line.endswith(".")
    assert trouble.quiet_for >= 60.0
