"""Questions Marvi puts on screen, and what happened to them.

Asking out loud is the right way to ask most things. It is the wrong way to ask
for a spelling, an address, an API host, a date -- anything where hearing it
back wrong costs more than the question saved. For those she can put a box on
screen and let them type.

The reason this is a module rather than a tool that fires and forgets is the
half that was missing. Marvi asks, and then:

* they type an answer -- fine, and the easy case;
* they close it without answering;
* they leave it sitting there and go back to what they were doing;
* they answer it with something that is not an answer.

Only the first of those is a question that got asked. The other three are a
question that is still open, and an assistant that does not know the difference
has not asked anything -- she has produced a dialog. So every question keeps
its state, and a question that was never answered comes back **once**, out
loud, where it cannot be closed with a mouse.

## Once, and then never

The point of asking on screen is to be less annoying than asking aloud, and a
question that returns forever is more annoying than one that was never asked.
So: one written attempt, one spoken follow-up, and then it is `given_up` and
Marvi does not raise it again. Somebody who closed a box and then ignored a
spoken question has answered, and the answer is no.

`declined` is different and stronger: it is the user saying not to ask, and it
is permanent from the first time they say it.

## Why it is on disk

The commonest way to not answer a question is to walk away from it, and the
second commonest is to close the laptop. A store that emptied on restart would
lose exactly the questions this exists to follow up.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .logs import get_logger
from .paths import identity_dir

log = get_logger("gateway")

#: How long a question stays on screen before it counts as ignored.
#:
#: Ten minutes. Long enough that stepping away for coffee does not turn into a
#: spoken question when they sit back down; short enough that the follow-up
#: still belongs to the conversation that produced it.
IGNORED_AFTER = 600.0

#: How long a settled question is kept, so `status` can still answer about it.
#:
#: A day. Marvi needs to be able to say "you told me on Tuesday" without the
#: store becoming a second memory -- the answer itself goes to memory, and this
#: is only the record of having asked.
FORGET_AFTER = 86_400.0

OPEN = "open"
ANSWERED = "answered"
DISMISSED = "dismissed"
IGNORED = "ignored"
ASKED_ALOUD = "asked_aloud"
GIVEN_UP = "given_up"
DECLINED = "declined"

#: States where nothing more will happen.
SETTLED = frozenset({ANSWERED, GIVEN_UP, DECLINED})


class Settled(BaseModel):
    """What the desktop reports back when the user finishes with a box.

    Defined here rather than inside `asking_router`, and that is not style.
    With `from __future__ import annotations` every annotation is a string, and
    FastAPI resolves them against the *module* namespace -- so a model declared
    inside the factory cannot be found, and the body silently becomes a query
    parameter. The symptom is a 422 saying `loc: ["query", "body"]` on a
    request whose body is perfectly good.
    """

    state: str
    answer: str = ""


@dataclass
class Question:
    """One thing Marvi asked for in writing."""

    id: str
    question: str
    #: What it is about, so an answer can be filed. Free text; `curiosity` uses
    #: its gap key here.
    about: str = ""
    #: A hint for the box, not a default. Never pre-fill an answer.
    placeholder: str = ""
    state: str = OPEN
    answer: str = ""
    asked_at: float = field(default_factory=time.time)
    settled_at: float = 0.0

    @property
    def waiting(self) -> bool:
        return self.state == OPEN

    def stale(self, now: float | None = None) -> bool:
        """Whether it has been sitting unanswered long enough to count as ignored."""
        return self.state == OPEN and (now or time.time()) - self.asked_at > IGNORED_AFTER

    def needs_saying_aloud(self, now: float | None = None) -> bool:
        """Whether this is a question Marvi still owes the user out loud.

        Closed on purpose or left alone -- both mean the written question did
        not work, and both get exactly one spoken attempt.
        """
        return self.state == DISMISSED or self.stale(now)

    def plainly(self) -> str:
        """How to describe the state to the model, in words rather than a code."""
        return {
            OPEN: "still on screen, not answered yet",
            ANSWERED: "answered",
            DISMISSED: "closed without answering",
            IGNORED: "left on screen unanswered",
            ASKED_ALOUD: "asked out loud after the box was not used",
            GIVEN_UP: "asked twice, never answered; do not ask again",
            DECLINED: "they said not to ask; never ask again",
        }.get(self.state, self.state)


class Asking:
    """Every question Marvi has put on screen lately."""

    def __init__(self, path: Any = None) -> None:
        self.path = Path(path) if path else identity_dir() / "asking.json"
        self._questions: dict[str, Question] = {}
        self._load()

    def _load(self) -> None:
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for row in rows if isinstance(rows, list) else []:
            try:
                one = Question(**row)
            except TypeError:
                continue
            self._questions[one.id] = one

    def _save(self) -> None:
        now = time.time()
        keep = [
            asdict(one)
            for one in self._questions.values()
            if one.state not in SETTLED or now - (one.settled_at or one.asked_at) < FORGET_AFTER
        ]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(keep, indent=2), encoding="utf-8")
        except OSError as exc:  # pragma: no cover - depends on the disk
            log.warning("could not write the question store: %s", exc)

    def ask(self, question: str, about: str = "", placeholder: str = "") -> Question:
        """Put a question on screen. Refuses to ask the same thing twice.

        A second box for a question already waiting is two boxes for one
        answer, and a box for something they declined is the one thing
        `declined` exists to prevent.
        """
        text = " ".join((question or "").split())[:300]
        if not text:
            raise ValueError("A question needs words in it.")
        for one in self._questions.values():
            if one.state == DECLINED and one.about and one.about == about:
                raise ValueError(
                    f"They asked not to be asked about {about}. Do not ask again, "
                    "in writing or out loud."
                )
            if one.waiting and (one.question == text or (about and one.about == about)):
                raise ValueError(
                    f"That is already on screen, unanswered (question {one.id}). "
                    "Wait for it, or read its status."
                )
        asked = Question(
            id=uuid.uuid4().hex[:8], question=text, about=about,
            placeholder=" ".join((placeholder or "").split())[:80],
        )
        self._questions[asked.id] = asked
        self._save()
        log.info("asked on screen: %s (%s)", asked.id, about or "no subject")
        return asked

    def settle(self, question_id: str, state: str, answer: str = "") -> Question:
        """Record what the user did with it."""
        one = self._questions.get(question_id)
        if one is None:
            raise ValueError("No such question.")
        one.state = state
        one.answer = " ".join((answer or "").split())[:500]
        one.settled_at = time.time()
        self._save()
        log.info("question %s is now %s", question_id, state)
        return one

    def waiting(self) -> list[Question]:
        """What is on screen right now, oldest first."""
        return sorted(
            (one for one in self._questions.values() if one.waiting),
            key=lambda one: one.asked_at,
        )

    def owed_aloud(self, now: float | None = None) -> list[Question]:
        """Questions the written attempt did not answer, for the mind to raise.

        This is the follow-through. Without it, asking on screen is strictly
        worse than asking aloud: the same interruption, and no answer.
        """
        return [one for one in self._questions.values() if one.needs_saying_aloud(now)]

    def mark_asked_aloud(self, question_id: str) -> Question:
        """One spoken attempt used. After this it is `given_up`, not repeated."""
        return self.settle(question_id, ASKED_ALOUD)

    def give_up(self, question_id: str) -> Question:
        return self.settle(question_id, GIVEN_UP)

    def status(self, question_id: str = "") -> dict[str, Any]:
        """What the model reads. States in words, never codes."""
        if question_id:
            one = self._questions.get(question_id)
            if one is None:
                return {"found": False, "detail": "No question with that id."}
            return {
                "found": True, "id": one.id, "question": one.question,
                "state": one.plainly(), "answer": one.answer,
                "waiting": one.waiting,
            }
        recent = sorted(self._questions.values(), key=lambda o: -o.asked_at)[:10]
        return {
            "on_screen_now": [
                {"id": o.id, "question": o.question, "seconds_waiting": round(time.time() - o.asked_at)}
                for o in self.waiting()
            ],
            "recent": [
                {"id": o.id, "question": o.question, "state": o.plainly(), "answer": o.answer}
                for o in recent
            ],
        }

    def forget(self) -> None:
        self._questions.clear()
        self._save()


def register_asking_tools(registry: Any, store: Asking) -> None:
    """`ask_on_screen` and `ask_on_screen_status`.

    Two tools, not one. Asking and finding out what happened are separate acts
    separated by minutes, and a single tool that did both would have to block
    or lie about which it did.
    """
    from .tools import ToolSpec

    def ask(question: str, about: str = "", placeholder: str = "") -> dict[str, Any]:
        one = store.ask(question, about, placeholder)
        return {
            "id": one.id,
            "state": one.plainly(),
            "detail": (
                "The box is on their screen. Do not wait for it and do not ask the same "
                "thing out loud -- carry on, and read ask_on_screen_status later. If they "
                "close it or leave it, you will be told to ask once out loud."
            ),
        }

    registry.register(
        ToolSpec(
            name="ask_on_screen",
            description=(
                "Put a question on the user's screen with a box to type into. Use it when "
                "hearing the answer wrong would be worse than the question -- a spelling, "
                "an address, a URL, an account name, a date. Not for anything a spoken "
                "answer handles well, and never for a password or key: ask_secret is for "
                "those. It returns immediately with an id; the answer is not available "
                "yet. Do not announce that you have opened a box and do not wait for it -- "
                "carry on with the conversation and read ask_on_screen_status later."
            ),
            arguments={"question": str},
            optional={"about": str, "placeholder": str},
            sensitive=False,
            handler=ask,
            describes={
                "question": "The question, as you would say it. One sentence.",
                "about": "What it is about, so the answer can be filed -- 'name', 'work'.",
                "placeholder": "A hint for the empty box. Never an answer.",
            },
        )
    )
    registry.register(
        ToolSpec(
            name="ask_on_screen_status",
            description=(
                "What happened to a question you put on screen: still waiting, answered "
                "and with what, closed without answering, or left alone. Read it before "
                "assuming an answer and before asking the same thing again. Omit the id "
                "for everything recent."
            ),
            arguments={},
            optional={"question_id": str},
            sensitive=False,
            handler=lambda question_id="": store.status(question_id),
            describes={"question_id": "The id ask_on_screen returned. Omit for all recent."},
        )
    )


def asking_router(store: Asking, audit: Any = lambda *_: None) -> Any:
    """What the desktop posts back when the user types, closes, or declines."""
    from fastapi import APIRouter, Depends, HTTPException

    from .localauth import guard

    router = APIRouter(prefix="/asking", dependencies=[Depends(guard)])

    @router.get("")
    def on_screen() -> dict[str, Any]:
        return {
            "waiting": [asdict(one) for one in store.waiting()],
            "owed_aloud": [asdict(one) for one in store.owed_aloud()],
        }

    @router.post("/{question_id}")
    def settle(question_id: str, body: Settled) -> dict[str, Any]:
        allowed = {ANSWERED, DISMISSED, DECLINED}
        if body.state not in allowed:
            raise HTTPException(422, f"state must be one of {sorted(allowed)}")
        # The answer is the user's own words and never reaches the audit line.
        audit("asking", "answered_on_screen", {"question_id": question_id, "state": body.state})
        try:
            one = store.settle(question_id, body.state, body.answer)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"ok": True, "state": one.plainly()}

    return router
