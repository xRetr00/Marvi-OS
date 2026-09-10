"""Questions Chat asks *inside* a turn, and waits for.

`clarify` and `ask_secret` post to the voice surface and return immediately.
That is right for voice -- a spoken session cannot hold a turn open while
somebody reads -- and it is why both tools ended up on the Dynamic Island no
matter which surface asked. Chat has no Island, so the card went to the voice
page and the conversation the user was actually looking at showed nothing.

## Chat can block, and should

A typed conversation has no live audio to stall. The turn is already running
on a worker thread with a cancellation flag, so waiting costs nothing that
was not already being spent, and it buys the thing the voice path gives up:
the answer arrives as a tool *result*, in the same turn, so the model does not
have to be told to stop and wait and then be trusted to actually do it.

## The registry is the channel

There is no `channel` field anywhere here, deliberately. Chat intercepts these
two tools in its own tool loop and routes them through this module; anything
that does not go through Chat's loop reaches the voice surface exactly as
before. Where the code lives is the routing, so there is no flag to set wrong.

## Nothing here ever holds a secret

An `ask_secret` answer settles as the word "saved" or "skipped". The value goes
desktop -> `POST /voice/secret` -> settings store, the same single path it has
always taken, and never passes through this module, the turn, or the model.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from pydantic import BaseModel

from .logs import get_logger

log = get_logger("gateway")

#: How long a turn will sit on a question before giving up on it. Long enough
#: to read a question and type an answer; short enough that a window closed
#: mid-question does not pin a worker thread for the life of the process.
INLINE_TTL_SECONDS = 300.0

#: How often the wait wakes to check whether the turn was cancelled. The client
#: disconnecting sets that flag, and a turn nobody is watching should not go on
#: holding a thread until the full timeout runs out.
POLL_SECONDS = 0.25


class InlineAsk(BaseModel):
    """One question on screen, in the transcript, being waited on."""

    id: str
    kind: str  # "clarify" | "secret"
    question: str = ""
    choices: list[str] = []
    multi_select: bool = False
    #: `ask_secret` only: the setting name the value is stored under.
    name: str = ""
    why: str = ""
    asked_at: float = 0.0

    def stale(self, now: float | None = None) -> bool:
        return (now or time.time()) - self.asked_at > INLINE_TTL_SECONDS


class InlineAsks:
    """Open questions, keyed by id, each with a thread waiting on it.

    One lock, one dict, one event per question. There is no throughput story
    here worth a finer-grained design: the number of questions in flight is
    bounded by the number of chat turns in flight, which is one.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open: dict[str, tuple[InlineAsk, threading.Event]] = {}
        self._answers: dict[str, str] = {}

    def open(self, ask: InlineAsk) -> InlineAsk:
        with self._lock:
            self._open[ask.id] = (ask, threading.Event())
        return ask

    def waiting(self) -> list[InlineAsk]:
        with self._lock:
            return [ask for ask, _ in self._open.values() if not ask.stale()]

    def settle(self, ask_id: str, answer: str) -> bool:
        """Record an answer and wake the turn. False when nothing was waiting.

        A late settle -- the turn already timed out and moved on -- is a miss,
        not an error. The caller reports it so the window can stop drawing a
        card nobody is listening for any more.
        """
        with self._lock:
            entry = self._open.get(ask_id)
            if entry is None:
                return False
            self._answers[ask_id] = answer
            entry[1].set()
        return True

    def wait(
        self,
        ask_id: str,
        cancelled: Callable[[], bool] | None = None,
        timeout: float = INLINE_TTL_SECONDS,
    ) -> str | None:
        """Block until answered, cancelled, or out of time.

        Returns the answer, or None when nobody answered. None is a real
        outcome the caller has to handle -- it is what a closed window looks
        like -- so it is never raised.
        """
        with self._lock:
            entry = self._open.get(ask_id)
        if entry is None:
            return None
        _, event = entry
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                if cancelled is not None and cancelled():
                    return None
                if event.wait(POLL_SECONDS):
                    with self._lock:
                        return self._answers.get(ask_id)
            return None
        finally:
            self.close(ask_id)

    def close(self, ask_id: str) -> None:
        with self._lock:
            self._open.pop(ask_id, None)
            self._answers.pop(ask_id, None)

    def forget(self) -> None:
        """Wake everything and drop it. For shutdown and for tests."""
        with self._lock:
            for _, event in self._open.values():
                event.set()
            self._open.clear()
            self._answers.clear()


#: The process-wide registry. Chat's tool loop writes to it, the settle route
#: reads it, and nothing else touches it.
ASKS = InlineAsks()


def inline_router(store: InlineAsks) -> Any:
    """`POST /chat/ask/{id}` -- the window handing an answer back to a turn."""
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel as Body

    router = APIRouter()

    class Answer(Body):
        answer: str = ""

    @router.post("/chat/ask/{ask_id}")
    def settle(ask_id: str, body: Answer) -> dict[str, Any]:
        answer = " ".join((body.answer or "").split()).strip()
        if not answer:
            raise HTTPException(status_code=400, detail="an answer is required")
        if not store.settle(ask_id, answer):
            # 409 rather than 404: the question existed, the turn stopped
            # waiting. The window needs to tell those apart to know whether
            # retrying could ever work.
            raise HTTPException(status_code=409, detail="nothing is waiting on that question")
        log.info("inline ask settled", extra={"marvi_ask": ask_id})
        return {"settled": True, "id": ask_id}

    @router.get("/chat/ask")
    def waiting() -> dict[str, Any]:
        return {"waiting": [ask.model_dump() for ask in store.waiting()]}

    return router
