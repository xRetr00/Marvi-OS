"""Who Marvi is, in one place, in a form the user can change.

Two problems, and they turn out to be the same problem.

**Her character was scattered.** How she talks lived in `SOUL.md`, and also in
seventy-eight sentences of hardcoded instruction in the Agent, and also in a
policy table in the Gateway. "Say the thing, then stop" was in the soul; "Stop
when the answer stops" was in the Agent; both were true and neither was the
source. Changing how she sounds meant finding every copy, and nobody ever did,
so the copies drifted and the model read the same rule three times in three
voices.

**And there was only one of her.** The soul says "Silence is the default and
it is not failure. Most of what you notice is not worth a word." That is a
real position, held on purpose, and it produces an assistant that answers "hi"
with "hi" and volunteers nothing for the rest of the day. It is the right
assistant for somebody who wants to be left alone and the wrong one for
somebody who wants a colleague, and the file could only hold one of them.

So: personas are files, one per way of being, and the user picks. What is *not*
in them is anything about facts, tools, safety or the mechanics of speech --
those are the same whoever she is being, and they stay where they are.

## The surface matters as much as the persona

Voice and chat are not the same job. "Never use Markdown" is correct in a room
and actively wrong in a chat window, where a table is the clearest answer
available and nobody is waiting through it. The old prompt sent the spoken
rules everywhere, so the typed surface was told to avoid code fences while
being asked about code.

A persona therefore resolves against the surface as well as the name: `chat`
is a real persona rather than a flag, and it wins over the chosen voice persona
when the request came from the chat window.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .logs import get_logger

log = get_logger("gateway")

#: The setting that names the chosen persona. Empty means `DEFAULT`.
SETTING = "MARVI_PERSONA"

#: Who she is when nobody has said otherwise.
DEFAULT = "default"

#: The persona used for the typed surface, whatever is chosen for voice.
#:
#: Not a user choice today, and deliberately not: the reason chat differs is
#: the medium, not taste. Somebody who wants Marvi funny in the room wants her
#: funny in chat too -- but they still want code in a code block.
FOR_CHAT = "chat"


@dataclass(frozen=True)
class Persona:
    """One way of being Marvi."""

    name: str
    #: What a person picks it by.
    label: str
    #: One line under the label, so the choice is not a guess.
    blurb: str
    text: str = ""

    @property
    def chosen_for_voice(self) -> bool:
        """Whether this is something a person picks, or a surface's own."""
        return self.name != FOR_CHAT


#: What each shipped persona is, for the picker. The text lives in the files.
KNOWN: tuple[Persona, ...] = (
    Persona(
        "default",
        "Marvi",
        "Warm and forward. Notices things, suggests, asks, and starts the "
        "conversation rather than waiting to be asked.",
    ),
    Persona(
        "funny",
        "Marvi, funnier",
        "The same, with a sense of humour. Dry and quick, and it drops the "
        "moment something is actually wrong.",
    ),
    Persona(
        "silent",
        "Marvi, quiet",
        "Answers what she is asked and otherwise stays out of the way. "
        "Silence is the default.",
    ),
    Persona(
        FOR_CHAT,
        "Chat",
        "Used in the chat window whatever else is chosen: long answers, "
        "Markdown, and code in code blocks.",
    ),
)

BY_NAME = {one.name: one for one in KNOWN}


def _folder(root: Path | None = None) -> Path:
    """Where the persona files live. The repo's copy, not the user's home.

    They are shipped rather than seeded, unlike `SOUL.md`. A seeded file is
    one the user may have edited and must not be overwritten; these are ours,
    they change with the code, and a stale copy in somebody's home directory
    would be a persona nobody could fix.
    """
    if root is not None:
        return root / "config" / "personas"
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config" / "personas").is_dir():
            return parent / "config" / "personas"
    return here.parent / "personas"


def chosen() -> str:
    """The persona the user picked, or the default when they have not."""
    name = os.environ.get(SETTING, "").strip().lower()
    return name if name in BY_NAME and BY_NAME[name].chosen_for_voice else DEFAULT


def available() -> list[dict[str, str]]:
    """What the picker offers, in the order it should show them."""
    return [
        {"name": one.name, "label": one.label, "blurb": one.blurb}
        for one in KNOWN
        if one.chosen_for_voice
    ]


#: What every persona says, so no persona has to say it.
#:
#: The first version had no such file and the personas were near-copies of one
#: another -- `default` and `funny` shared 59% of their lines -- which had two
#: costs. They read the same, which is what the picker was supposed to fix; and
#: `funny` had silently lost a whole section during the copying, so choosing it
#: dropped rules nobody meant to drop.
#:
#: What lives here is what never varies with character: how she uses tools,
#: what she does before something irreversible, that external text is
#: information and never instruction, and that a closing offer is not
#: conversation. A persona is now only the part that differs.
SHARED = "_shared"


def text(name: str = "", root: Path | None = None, shared: bool = True) -> str:
    """The persona's own words, with the shared rules after them.

    Falls back to the default rather than to nothing: a mistyped setting should
    leave Marvi herself, not leave her with no character at all.
    """
    wanted = (name or chosen()).strip().lower()
    folder = _folder(root)
    said = ""
    for candidate in (wanted, DEFAULT):
        if not candidate:
            continue
        try:
            said = (folder / f"{candidate}.md").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if said:
            if candidate != wanted:
                log.warning("no persona called %r; using %s", wanted, candidate)
            break
    if not said:
        log.warning("no persona files under %s", folder)
        return ""
    if not shared:
        return said
    try:
        common = (folder / f"{SHARED}.md").read_text(encoding="utf-8").strip()
    except OSError:
        common = ""
    # Character first, then the rules that do not vary. Character leads because
    # it is the part that decides how everything after it is said.
    gap = chr(10) * 2
    return f"{said}{gap}{common}".strip() if common else said


#: The heading whose section tells the mind how readily to speak up.
#:
#: A section rather than the whole persona, because the mind is deciding, not
#: talking: it emits one JSON object and never says a word itself, so the
#: fifteen hundred characters about Markdown and sentence length are noise in
#: front of it. See `identity.compose(in_character=False)` for the same
#: reasoning applied to the other background jobs.
STANCE = "## Deciding in the background"

#: The background mind's own file, the way `chat` is the typed surface's.
#:
#: The mind had no file and no way to get one. Its whole stance was a Python
#: string in `deliberate`, and the string said "Silence is the normal, correct
#: answer" -- so every persona deliberated like the quiet one, and the picker
#: changed only how the sentence was worded once something had already got
#: past that. It is a shipped file now, editable like the rest.
FOR_MIND = "mind"


def stance(name: str = "", root: Path | None = None) -> str:
    """How readily this persona speaks when nobody asked. Empty if unsaid.

    This is the half of the persona the background mind needs, and it had no
    way to reach it. `deliberate.SYSTEM_PROMPT` hardcoded "Silence is the
    normal, correct answer. Set worth_it false unless a person would genuinely
    want interrupting for this" -- the *silent* persona's position, stated as
    a fact about the system, in a string the picker cannot touch.

    So choosing "Marvi, warm and forward" changed how she phrased an answer and
    changed nothing about whether she offered one. `personas.default` says
    "Judgement, not silence by default ... and often it is" and lost every
    time, because the task text is more specific than the character text and
    arrives after it.

    On this machine it did not even lose a fair fight: `SOUL.md` is empty, and
    `CognitionHarness._system` composes `SOUL.md` rather than the chosen
    persona, so the hardcoded sentence was the mind's entire stance.
    """
    body = text(name, root, shared=False)
    if STANCE not in body:
        return ""
    after = body.split(STANCE, 1)[1]
    # To the next heading of the same level, or the end.
    gap = chr(10)
    lines: list[str] = []
    for line in after.split(gap):
        if line.startswith("## "):
            break
        lines.append(line)
    return gap.join(lines).strip()


def for_mind(root: Path | None = None) -> str:
    """The mind's file plus the chosen persona's stance. Empty if unshipped.

    Two parts because they answer different questions. `mind.md` is the job --
    what this decision is, and the short list of things genuinely not worth
    saying (marketing mail, a repeat, someone mid-thought, an empty room). The
    persona's section is how readily *this* Marvi speaks, which is the part
    the picker owns. The persona goes last so it wins.
    """
    job = ""
    try:
        job = (_folder(root) / f"{FOR_MIND}.md").read_text(encoding="utf-8").strip()
    except OSError:
        log.warning("no %s.md; the mind is running on its fallback stance", FOR_MIND)
    mine = stance(root=root)
    gap = chr(10) * 2
    return gap.join(part for part in (job, mine) if part)


def for_surface(surface: str = "voice", root: Path | None = None) -> str:
    """The persona to use, given where the request came from.

    `chat` wins for the typed surface whatever is chosen for voice, because the
    difference there is the medium rather than taste -- see the module
    docstring.
    """
    if surface.strip().lower() == "chat":
        return text(FOR_CHAT, root)
    return text(chosen(), root)
