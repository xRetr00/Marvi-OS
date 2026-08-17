"""Retrying, bounded, and only where it is safe.

One helper rather than a different `for` loop per call site, because the parts
people leave out are always the same three: the jitter, the total-time cap, and
surfacing the failure at the end.

## Jitter is not decoration

Several subsystems retrying on the same schedule reconverge and hit the failing
thing together, which is an outage of its own making. The wait is randomised
across a window rather than doubled exactly.

## The rule that matters more than any of it

**Retry is safe for reads and unsafe for sends.** Re-reading a room state twice
costs nothing; re-sending an email twice is a second email. Phase 5 drew that
line with `spec.external`, and `retry` refuses to cross it: an operation marked
`repeatable=False` is attempted once and its failure is returned as-is.

That refusal is deliberate friction. Anyone who wants an external write retried
has to say so at the call site, in the open, where a reviewer will see it.

## A retry that ends in silence is worse than the original error

The caller waited longer *and* still has nothing. Every path here either
returns a value or raises the last exception with the attempt count attached.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .logs import get_logger

log = get_logger("retry")

DEFAULT_ATTEMPTS = 4
DEFAULT_BASE_SECONDS = 0.5
DEFAULT_MAX_SECONDS = 8.0
# A cap on total elapsed time as well as on attempts. Four attempts with a long
# backoff can still leave someone staring at a spinner for a minute.
DEFAULT_BUDGET_SECONDS = 20.0


class RetriesExhaustedError(Exception):
    """Every attempt failed. Carries the last cause."""

    def __init__(self, what: str, attempts: int, cause: BaseException) -> None:
        super().__init__(f"{what} failed after {attempts} attempts: {cause}")
        self.attempts = attempts
        self.cause = cause


@dataclass(frozen=True)
class Policy:
    attempts: int = DEFAULT_ATTEMPTS
    base_seconds: float = DEFAULT_BASE_SECONDS
    max_seconds: float = DEFAULT_MAX_SECONDS
    budget_seconds: float = DEFAULT_BUDGET_SECONDS
    #: False for anything that reaches outside this machine and cannot be undone
    #: by doing it again. Such an operation is attempted exactly once.
    repeatable: bool = True
    #: True when the thing being called is optional and being absent is a normal
    #: state, not a fault. Exhausting the retries is still logged, but not as an
    #: error: a sidecar the user never installed filled errors.log with one
    #: entry per poll, which buries the failures that do mean something.
    optional: bool = False

    def wait_for(self, attempt: int, rng: random.Random | None = None) -> float:
        """Exponential, capped, with full jitter.

        Full jitter — a uniform draw from `[0, backoff]` rather than
        `backoff ± a bit` — because it spreads retries the widest, and spreading
        is the entire purpose.
        """
        ceiling = min(self.base_seconds * (2 ** max(0, attempt - 1)), self.max_seconds)
        return (rng or random).uniform(0, ceiling)


READ_ONLY = Policy()
#: For a send, a purchase, a delete. Attempted once, and the failure is the
#: answer.
EXTERNAL_WRITE = Policy(attempts=1, repeatable=False)
#: Reconnects can afford to be patient; nobody is waiting on a first token.
RECONNECT = Policy(attempts=6, base_seconds=1.0, max_seconds=30.0, budget_seconds=120.0)


def retry[T](
    operation: Callable[[], T],
    what: str = "operation",
    policy: Policy = READ_ONLY,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    give_up_on: tuple[type[BaseException], ...] = (),
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    rng: random.Random | None = None,
) -> T:
    """Run `operation`, retrying per `policy`. Returns its value or raises.

    `give_up_on` wins over `retry_on`: a rejected credential and a malformed
    request will not become valid on the third attempt, and retrying them just
    adds delay to a failure that was already certain.
    """
    if not policy.repeatable and policy.attempts != 1:
        # A policy that says "not repeatable" and then allows several attempts
        # is a contradiction, and the safe reading is the cautious one.
        policy = Policy(**{**policy.__dict__, "attempts": 1})

    started = now()
    last: BaseException | None = None

    for attempt in range(1, policy.attempts + 1):
        try:
            result = operation()
        except give_up_on:
            raise
        except retry_on as exc:
            last = exc
            if attempt >= policy.attempts:
                break
            wait = policy.wait_for(attempt, rng)
            if now() - started + wait > policy.budget_seconds:
                log.log(
                    logging.INFO if policy.optional else logging.WARNING,
                    "%s: out of time after %d attempts", what, attempt,
                    extra={"marvi_error": str(exc)[:200]},
                )
                break
            log.info(
                "%s failed, retrying in %.1fs", what, wait,
                extra={"marvi_attempt": attempt, "marvi_error": str(exc)[:200]},
            )
            sleep(wait)
        else:
            if attempt > 1:
                log.info("%s succeeded on attempt %d", what, attempt)
            return result

    assert last is not None
    # Never silent. The caller waited longer and still has nothing, so the
    # least it gets is the reason.
    log.log(
        logging.INFO if policy.optional else logging.ERROR,
        "%s gave up",
        what,
        extra={"marvi_error": str(last)[:200]},
    )
    raise RetriesExhaustedError(what, policy.attempts, last)


def once[T](operation: Callable[[], T], what: str = "operation") -> T:
    """Explicitly no retry. Reads at the call site as a decision, not a lapse."""
    return retry(operation, what, policy=EXTERNAL_WRITE)


def is_repeatable(spec: Any) -> bool:
    """Whether a tool may be retried.

    `spec.external` is Phase 5's marker for an action that reaches outside this
    machine. Anything unrecognised is treated as unsafe, because guessing wrong
    in the other direction sends a second email.
    """
    external = getattr(spec, "external", None)
    if external is None:
        return False
    return not external


def policy_for(spec: Any) -> Policy:
    return READ_ONLY if is_repeatable(spec) else EXTERNAL_WRITE
