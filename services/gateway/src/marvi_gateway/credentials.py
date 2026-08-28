"""Asking for a password, and reading a file that has one in it.

An assistant that sets things up needs credentials, and the two obvious ways of
getting them are both wrong. Refusing outright makes her useless for the exact
tasks people most want delegated. Letting her ask out loud and repeat the
answer back puts an API key through a speech recogniser, into a transcript, and
into a model provider's logs.

## The value never reaches the model

`ask_secret` puts a masked field on screen and returns the fact that it asked.
The user types the key there; the desktop sends it straight to the settings
store; Marvi is told it was saved, by name. She can then use it -- the process
that makes the request reads it from the environment -- without it ever having
been in her context.

This is the pattern every published guide on the subject converges on: code
references an abstract name, the value is injected at the point of use, and the
model handles the name. The difference between that and "she asked and you told
her" is the difference between a key on your machine and a key in somebody's
inference logs.

That is also why the answer to this does *not* go into the room the way a
`clarify` answer does. A clarify answer is meant to be part of the
conversation. This one must never be.

## Reading a file that has secrets in it

Three settings rather than a block, because the block was wrong and "let her
read everything" is also wrong:

* **off** -- refused, which is the default.
* **masked** -- she reads the file and sees `OPENROUTER_API_KEY=sk-or-****`.
  This answers nearly every real question -- which variables are set, which one
  is missing, whether the name is spelled right -- without a key leaving the
  machine.
* **full** -- the real values, and they go wherever the conversation goes.

Masked is the interesting one and the reason this is not a two-way switch.
"Is my key set?" and "what is my key?" look like the same question and are not.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

from pydantic import BaseModel

from .logs import get_logger

log = get_logger("gateway")

SETTING = "MARVI_SECRET_ACCESS"
OFF, MASKED, FULL = "off", "masked", "full"
LEVELS = (OFF, MASKED, FULL)

#: How much of a value survives masking. Enough to recognise which key it is --
#: `sk-or-` versus `sk-ant-` -- and not enough to use.
KEPT = 6

#: How long a request sits on screen before it stops sitting there. Longer than
#: a question: fetching a key from a password manager is a minute's work, and a
#: field that vanished while you were looking for it is worse than useless.
REQUEST_TTL_SECONDS = 900.0

#: `NAME=value`, and the JSON-ish `"name": "value"`. Between them they cover
#: .env files, INI files and credential JSON, which is what this is for.
_ASSIGNMENT = re.compile(r"^(\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_.\-]*\s*=\s*)(.*)$")
_JSON_FIELD = re.compile(r'^(\s*"[^"]+"\s*:\s*")([^"]*)(".*)$')


def level() -> str:
    """What Marvi may do with a secret file. Unreadable values mean off."""
    value = os.environ.get(SETTING, "").strip().lower()
    return value if value in LEVELS else OFF


def mask(value: str) -> str:
    """A value reduced to what identifies it, and nothing that uses it."""
    text = value.strip().strip("\"'")
    if not text:
        return ""
    if len(text) <= KEPT:
        return "*" * len(text)
    return f"{text[:KEPT]}{'*' * min(len(text) - KEPT, 12)}"


def mask_text(text: str) -> str:
    """A whole file with its values masked and its shape intact.

    The shape is the point: which names are there, which are empty, what order
    they are in, which section they are under. That is the part somebody
    debugging a configuration actually needs.
    """
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith(";") or not stripped:
            lines.append(line)
            continue
        assignment = _ASSIGNMENT.match(line)
        if assignment:
            lines.append(f"{assignment.group(1)}{mask(assignment.group(2))}")
            continue
        field = _JSON_FIELD.match(line)
        if field:
            lines.append(f"{field.group(1)}{mask(field.group(2))}{field.group(3)}")
            continue
        lines.append(line)
    return "\n".join(lines)


class SecretRequest(BaseModel):
    """A masked field on screen, and what it is for."""

    id: str
    #: The setting it will be saved as, e.g. `OPENROUTER_API_KEY`.
    name: str
    #: Why Marvi is asking, in her words. The user is about to type a
    #: credential into a box; they are owed a reason.
    why: str = ""
    asked_at: float = 0.0

    def stale(self, now: float | None = None) -> bool:
        return (now or time.time()) - self.asked_at > REQUEST_TTL_SECONDS


#: Text that carries a credential, wherever it is about to be written down.
#:
#: This lives here rather than beside any one caller because every path that
#: persists text needs the same answer: memory, the after-turn worker, and an
#: import from another assistant.
#:
#: It is not hypothetical. A live Honcho account belonging to this project's
#: author held a university login password and a national ID number repeated
#: across **eight peers**, and a database role password in a ninth -- because an
#: assistant that is *told* a password writes it down like anything else, and
#: nothing had ever told it not to.
#:
#: The shape is: the word, and then something that looks like a value.
#: Requiring the value is what tells `password Misho2013` from `strong
#: credential and system blacklists`, which is a sentence about policy and was
#: refused by the first version of this. The gap is generous because the value
#: is often a clause away -- "the password for the university portal is X".
SECRETS = re.compile(
    r"\b(?:password|passwd|passphrase|api[_ -]?key|secret[_ -]?key|access[_ -]?token"
    r"|bearer|credentials?)\b"
    r"(?:[^.\n]{0,45}?\b(?=[A-Za-z0-9@#$%^&*!-]*[A-Za-z])(?=[A-Za-z0-9@#$%^&*!-]*\d)"
    r"[A-Za-z0-9@#$%^&*!-]{6,}\b|\s*[:=]\s*\S{4,})"
    # Identity numbers, keys with a known prefix, and long digit runs.
    r"|\b(?:TC|SSN|NIN)\b\s*:?\s*\d{6,}"
    r"|\b(?:iban|sort code|account number|card number)\b"
    r"|\b(?:sk|pk|ghp|gho|xox[bp])[-_][A-Za-z0-9]{16,}"
    r"|\b\d{11,19}\b",
    re.I,
)


def carries_a_secret(text: str) -> bool:
    """Whether this text must not be written down as it stands.

    The answer to a secret is never "store it more carefully" -- it is
    `ask_secret`, which puts the value in the settings store without it ever
    passing through the model. Anything that gets `True` here should refuse and
    say so, not mask and continue: a half-redacted memory still says where to
    look.
    """
    return bool(SECRETS.search(text or ""))


#: A setting name has to be one, or this becomes a way to write anywhere in the
#: settings store from a sentence.
VALID_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,64}$")


def register_secret_tool(registry: Any, runtime: Any) -> None:
    from .tools import ToolSpec

    def ask_secret(name: str, why: str = "") -> dict[str, Any]:
        setting = (name or "").strip().upper()
        if not VALID_NAME.match(setting):
            return {
                "asked": False,
                "error": f"{name!r} is not a setting name. Use the name the "
                "program reads, such as OPENROUTER_API_KEY.",
            }
        runtime.ask_secret(setting, " ".join((why or "").split()))
        log.info("ask_secret: asked for %s", setting, extra={"marvi_setting": setting})
        return {
            "asked": True,
            "name": setting,
            "note": (
                f"A masked field for {setting} is on screen. Say one short line "
                "pointing at it and stop. Never ask for the value out loud and "
                "never repeat it: you will be told when it is saved, by name, "
                "and you will never see it. It is saved as a setting, so "
                "anything that reads the environment can use it."
            ),
        }

    registry.register(
        ToolSpec(
            name="ask_secret",
            description=(
                "Ask the user for a password, API key or token. It goes into "
                "settings; you are told the name, never the value"
            ),
            arguments={"name": str},
            optional={"why": str},
            sensitive=False,
            handler=ask_secret,
            describes={
                "name": "The setting name the program reads, such as "
                "OPENROUTER_API_KEY or SMTP_PASSWORD. Upper case with "
                "underscores.",
                "why": "One sentence on what it is for. The user is about to "
                "type a credential into a box and is owed a reason.",
            },
        )
    )
