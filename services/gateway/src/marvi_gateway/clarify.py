"""Asking the user a question, with options, without stopping the conversation.

Marvi had two ways to handle not knowing something: guess, or ask in prose and
hope the answer came back in a shape she could use. Both are worse than they
sound on voice, where "which of these three did you mean" spoken as a paragraph
is a paragraph the user has to hold in their head while answering.

## Why it does not block

The obvious implementation waits for an answer and returns it. That is what a
command-line agent does, and it is wrong here: the session is a live
conversation, a tool that blocks holds the turn open, and the user is going to
answer by *talking* -- which is a new turn, not a return value.

So this posts the question and returns immediately. Marvi says it out loud,
the desktop draws it as buttons, and whichever way the user answers, the answer
arrives as their next turn. The tool's own result is the fact that the question
was asked, and the instruction to ask it aloud.

That also means it cannot deadlock, cannot time out, and works identically when
nobody is looking at the screen.

## Options are options, not prose

The choices go in `choices`, never written into the question text. Options
written into the question render as dead prose the user cannot click, and read
aloud as a list they cannot remember. The first is the recommendation, and the
surface says so; typing something else is always available and never needs to
be offered as a choice.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel

from .logs import get_logger

log = get_logger("gateway")

#: Four, as every surface that renders choices settles on. More than that spoken
#: aloud is a list nobody holds in their head, and the free-text answer covers
#: the tail anyway.
MAX_CHOICES = 4

#: Said on the recommended one. Presentation only: the answer that comes back
#: is the bare choice, so the model never reasons about the label.
RECOMMENDED = "(recommended)"

#: A question nobody answered stops being on screen. It is not cancelled --
#: the user may still answer out loud -- it just stops sitting there.
QUESTION_TTL_SECONDS = 300.0


class Question(BaseModel):
    """What is on screen, and what was asked."""

    id: str
    text: str
    choices: list[str] = []
    multi_select: bool = False
    asked_at: float = 0.0

    def stale(self, now: float | None = None) -> bool:
        return (now or time.time()) - self.asked_at > QUESTION_TTL_SECONDS


def _one_choice(value: Any) -> str:
    """A choice as the words the user will see.

    Models emit `[{"label": "..."}]` about as often as `["..."]`, and a bare
    `str()` on the dict puts a Python repr on the screen and then hands that
    repr back as the answer. Unwrapped here, at the one place every surface
    goes through, rather than in each of them.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("label", "description", "text", "title"):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return found.strip()
        return ""
    return str(value).strip() if value is not None else ""


def clean_choices(raw: Any) -> list[str]:
    """The offered options, in order, at most four, none of them empty."""
    if not isinstance(raw, list):
        return []
    return [choice for choice in (_one_choice(item) for item in raw) if choice][:MAX_CHOICES]


def as_shown(choices: list[str]) -> list[str]:
    """The choices as the user sees them, the first marked.

    A single choice is not a recommendation -- there is nothing to prefer it
    over -- so it is left alone. A model that wrote its own recommendation into
    the text is also left alone rather than given the label twice.
    """
    if len(choices) < 2:
        return list(choices)
    first = choices[0]
    if RECOMMENDED.strip("()").casefold() in first.casefold():
        return list(choices)
    return [f"{first} {RECOMMENDED}", *choices[1:]]


def bare(answer: str) -> str:
    """An answer with the label taken back off.

    The user picked the decorated string; the model asked about the bare one.
    Returning the decorated one leaks presentation into what Marvi then repeats
    back out loud.
    """
    text = (answer or "").strip()
    if text.casefold().endswith(RECOMMENDED.casefold()):
        return text[: -len(RECOMMENDED)].strip()
    return text


def register_clarify_tool(registry: Any, runtime: Any) -> None:
    from .tools import ToolSpec

    def clarify(question: str, choices: Any = None, multi_select: bool = False) -> dict[str, Any]:
        text = " ".join((question or "").split())
        if not text:
            return {"asked": False, "error": "a question is required"}
        offered = clean_choices(choices)
        asked = runtime.ask(text, offered, multi_select)
        log.info(
            "clarify: asked the user",
            extra={
                "marvi_question": text[:200],
                "marvi_choices": str(len(offered)),
                "marvi_multi_select": str(bool(multi_select)),
            },
        )
        return {
            "asked": True,
            "question": text,
            "choices": as_shown(offered),
            "id": asked.id,
            # The instruction is the useful half of this result. Without it a
            # model treats "asked: true" as the answer and carries on.
            "note": (
                "Say this question out loud now, and read the options. "
                "Then stop and wait: the answer arrives as the user's next "
                "message, whether they say it or press it. Do not call clarify "
                "again for the same question."
            ),
        }

    registry.register(
        ToolSpec(
            name="clarify",
            description="Ask the user a question and wait for their next answer",
            arguments={"question": str},
            optional={"multi_select": bool},
            sensitive=False,
            handler=clarify,
            describes={
                "question": "What you need to know, as one sentence. Never put "
                "the options in here -- they go in `choices`, and options "
                "written into the question cannot be pressed.",
                "choices": "Up to four options, best first: the first is shown "
                "as your recommendation. Typing something else is always "
                "available, so never offer 'other' as a choice. Omit entirely "
                "for an open question.",
                "multi_select": "True when more than one option can be picked "
                "at once. Default false.",
            },
            schema={
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "choices": {"type": "array", "items": {"type": "string"}},
                    "multi_select": {"type": "boolean"},
                },
                "required": ["question"],
            },
        )
    )
