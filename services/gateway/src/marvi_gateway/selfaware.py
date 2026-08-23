"""What Marvi is, where she lives, and how to read her own logs.

Two different kinds of self-knowledge, and they belong in two different places.

**Where she lives is a fact, and facts go in the prompt.** The install root,
the log directory, the running version, which models are loaded. It is true on
every turn and it is four lines, so making her call a tool to learn it would
cost a round trip to be told something that never changes. This is the same
slot the date goes in, for the same reason: the absence of it produced
confident wrong answers.

**Reading a log is an action, and actions are tools.** Which log, how much of
it, matching what -- that varies per question, and the answer is far too large
to carry around unasked.

## Why not the workspace tools

`file_read` and `terminal_run` already exist and are already careful. Pointing
`MARVI_WORKSPACE_ROOT` at the installation would have been less code and a
worse idea: the same root grants `file_write`, `file_delete` and
`terminal_run`, so the price of letting Marvi read her own logs would have been
letting her delete her own models. Reading is the part that is safe, so reading
is the part that is exposed.
"""

from __future__ import annotations

import os
from typing import Any

from . import paths

#: A tail, not a file. Logs here run to megabytes and the interesting part of
#: one is almost always the end.
MAX_LINES = 200
DEFAULT_LINES = 40
#: Long enough for a stack trace, short enough that a wide JSON line cannot
#: push everything else out of the reply.
MAX_LINE_CHARS = 400


def situation() -> str:
    """Where Marvi is installed and what she is running, for the prompt."""
    root = paths.root()
    lines = [
        f"- Installed at {root}",
        f"- Logs in {paths.logs_dir()}",
        f"- Skills in {paths.skills_dir()}; plugins in {root / 'plugins'}",
    ]
    nl = chr(10)
    return (
        "# Where you live"
        + nl
        + nl
        + nl.join(lines)
        + nl
        + nl
        + "This is your own installation, not the source repository it was "
        "built from. When something of yours is not working, `marvi_logs` "
        "reads these files -- prefer looking to guessing, and say what you "
        "actually found."
    )


def log_names() -> list[str]:
    directory = paths.logs_dir()
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir() if p.is_file() and p.suffix == ".log")


def read_log(name: str, lines: int = DEFAULT_LINES, contains: str = "") -> dict[str, Any]:
    """The tail of one log, optionally only the lines matching `contains`.

    Named rather than pathed: the argument is a file name inside the log
    directory and anything with a separator in it is refused, so this cannot
    be talked into reading somewhere else.
    """
    available = log_names()
    if os.sep in name or "/" in name or name.startswith("."):
        return {"ok": False, "detail": f"{name!r} is not a log name", "available": available}
    if not name.endswith(".log"):
        name = f"{name}.log"
    if name not in available:
        return {"ok": False, "detail": f"no log named {name}", "available": available}

    wanted = max(1, min(int(lines or DEFAULT_LINES), MAX_LINES))
    path = paths.logs_dir() / name
    try:
        # Read whole and slice: these are line-oriented text files a few
        # megabytes at worst, and a seek-backwards reader would be more code
        # than the saving is worth.
        found = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {"ok": False, "detail": str(exc), "available": available}

    if contains:
        needle = contains.lower()
        found = [line for line in found if needle in line.lower()]
    tail = [line[:MAX_LINE_CHARS] for line in found[-wanted:]]
    return {
        "ok": True,
        "log": name,
        "matched": len(found),
        "lines": tail,
        "available": available,
    }


def register_self_tools(registry: Any) -> None:
    from .tools import ToolSpec

    registry.register(
        ToolSpec(
            name="marvi_logs",
            description="Read Marvi's own logs",
            arguments={},
            optional={"name": str, "lines": int, "contains": str},
            describes={
                "name": (
                    "Which log: gateway, agent, voice, livekit, plugins, errors, "
                    "mind, chat, providers, desktop, installer. Omit to list them."
                ),
                "lines": f"How many lines from the end, up to {MAX_LINES}. Default {DEFAULT_LINES}.",
                "contains": "Only lines containing this text, matched case-insensitively.",
            },
            # Reading a log cannot change anything, and a fault is exactly when
            # asking permission is most annoying. Enveloped like any other read
            # by the router, because a log contains text from elsewhere.
            sensitive=False,
            handler=lambda name="", lines=DEFAULT_LINES, contains="": (
                read_log(name, lines, contains)
                if name
                else {"ok": True, "available": log_names(), "detail": "name one of these"}
            ),
        )
    )


def register_skill_tools(registry: Any) -> None:
    """Stage two of progressive disclosure, as one tool.

    The catalogue in the prompt is names and descriptions. This is how the
    instructions arrive, and only for the skill actually chosen.
    """
    from .setup import skills as skills_module
    from .tools import ToolSpec

    def skill_read(name: str) -> dict[str, Any]:
        try:
            skill = skills_module.body_of(name)
        except skills_module.SkillError as exc:
            return {
                "ok": False,
                "detail": str(exc),
                "available": [s.name for s in skills_module.installed()],
            }
        return {
            "ok": True,
            "name": skill.name,
            "description": skill.description,
            "instructions": skill.body.strip(),
        }

    registry.register(
        ToolSpec(
            name="skill_read",
            description="Read a skill's instructions",
            arguments={"name": str},
            describes={"name": "The skill's name, exactly as listed in the prompt."},
            sensitive=False,
            handler=skill_read,
        )
    )
