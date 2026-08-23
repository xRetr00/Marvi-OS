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
from pathlib import Path
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


# -- finding and installing skills --------------------------------------------

#: The store is nine repositories and one HTTP call each. Browsing them inside a
#: spoken turn would be seconds of silence, and the answer barely changes, so it
#: is held between calls.
CATALOGUE_TTL = 900
MAX_MATCHES = 8

_catalogue: tuple[float, list[dict[str, Any]]] | None = None


def find_skills(query: str, repo_root: Any = None, http: Any = None) -> dict[str, Any]:
    """Skills matching `query`: the ones Marvi already has, then the store.

    Hers come first and are listed even when nothing matches, because this tool
    answering only about the store produced the worst possible answer. Asked
    what skills she had, Marvi called `skill_find`, saw a library in which
    every row said "not installed", and told the user she loads no skills at
    all -- with eleven of them named in her own prompt at that moment.

    A tool called "find skills" that cannot find the skills you have is a trap,
    and the model walked into it exactly as written.
    """
    global _catalogue
    import time as _time

    from .setup import skills as skills_module
    from .setup import store

    root = repo_root or Path(__file__).resolve().parents[4]
    words = [w for w in query.lower().split() if len(w) > 2]

    def matches(name: str, description: str) -> int:
        if not words:
            return 1
        name, description = name.lower(), description.lower()
        return sum(4 * (w in name) + (w in description) for w in words)

    mine = [
        {
            "name": skill.name,
            "description": skill.description[:220],
            "repo": "",
            "installed": True,
            "have_it": True,
        }
        for skill in skills_module.installed()
        if matches(skill.name, skill.description)
    ]

    if _catalogue is None or _time.time() - _catalogue[0] > CATALOGUE_TTL:
        try:
            _catalogue = (_time.time(), store.catalogue(root, http))
        except Exception as exc:
            # Hers are on disk and do not need the network. A store that cannot
            # be reached must not hide the skills she is already carrying.
            return {
                "ok": True,
                "detail": f"the skill store is unreachable ({exc}); these are yours",
                "yours": mine,
                "skills": [],
            }

    rows = _catalogue[1]
    if words:
        def score(row: dict[str, Any]) -> int:
            # A word in the name is worth far more than a word in the
            # description: "brainstorm debugging" matched `astropy` on a
            # passing mention, and eight results ranked by nothing is a list
            # the model has to guess its way through.
            name = row["name"].lower()
            text = row["description"].lower()
            return sum(4 * (w in name) + (w in text) for w in words)

        rows = sorted(
            (row for row in rows if score(row)), key=lambda row: (-score(row), row["name"])
        )
    return {
        "ok": True,
        # Named separately from `skills` so there is no reading in which these
        # are something to install.
        "yours": mine,
        "total": len(_catalogue[1]),
        "matched": len(rows),
        "skills": [
            {
                "name": row["name"],
                "description": row["description"][:220],
                "repo": row["repo"],
                "installed": row["installed"],
            }
            for row in rows[:MAX_MATCHES]
        ],
    }


def install_skill(name: str, repo: str = "", repo_root: Any = None) -> dict[str, Any]:
    """Install one skill from a configured source.

    Two steps rather than one, because that is the flow the store already
    enforces: fetch and read it, then install what was read. A skill is
    instructions that change how Marvi behaves, written by someone else, so the
    body is parsed and its `allowed-tools` resolved against policy before
    anything is written to disk.
    """
    from .setup import store

    root = repo_root or Path(__file__).resolve().parents[4]
    found = find_skills(name, root)
    if not found.get("ok"):
        return found
    matches = [s for s in found["skills"] if s["name"] == name]
    if repo:
        matches = [s for s in matches if s["repo"] == repo]
    if not matches:
        return {
            "ok": False,
            "detail": f"no skill named {name!r} in the configured sources",
            "did_you_mean": [s["name"] for s in found["skills"][:5]],
        }
    if len({s["repo"] for s in matches}) > 1:
        return {
            "ok": False,
            "detail": f"{name!r} is in more than one source; say which",
            "repos": sorted({s["repo"] for s in matches}),
        }

    chosen = matches[0]
    row = next(
        (r for r in _catalogue[1] if r["name"] == name and r["repo"] == chosen["repo"]),
        None,
    )
    if row is None:  # pragma: no cover - only if the cache is cleared mid-call
        return {"ok": False, "detail": "that listing has expired; look again"}

    reviewed = store.review_remote(root, chosen["repo"], row["path"])
    if not reviewed.get("ok"):
        return reviewed
    outcome = store.install_reviewed(reviewed["staged"])
    # The catalogue's `installed` flags are now stale.
    globals()["_catalogue"] = None
    if outcome.get("ok"):
        outcome["detail"] = (
            f"installed {name} from {chosen['repo']}. "
            "It is usable now; read it with skill_read."
        )
    return outcome


def register_store_tools(registry: Any) -> None:
    """Letting Marvi extend herself, with the one guard that matters.

    A skill is instructions that shape her behaviour, fetched from the
    internet. Installing one is therefore a decision about her own conduct made
    on the user's machine, which is precisely the shape of thing that gets
    confirmed rather than assumed -- so finding is free and installing asks.

    She still cannot install from a source she found herself: both of these go
    through the configured source list, and a repository that is not on it is
    refused however the name arrived.
    """
    from .tools import ToolSpec

    registry.register(
        ToolSpec(
            name="skill_find",
            description="Search skills you have, and skills you could install",
            arguments={"query": str},
            describes={
                "query": (
                    "Words describing what you want to be able to do, for "
                    "example 'browser', 'debugging', 'spreadsheet'. Answers in "
                    "two parts: `yours` are already available through "
                    "skill_read, `skills` are in the store and are not."
                )
            },
            sensitive=False,
            handler=lambda query: find_skills(query),
        )
    )
    registry.register(
        ToolSpec(
            name="skill_install",
            description="Install a skill",
            arguments={"name": str},
            optional={"repo": str},
            describes={
                "name": "The skill's name, exactly as skill_find returned it.",
                "repo": "Which source, as owner/repo. Only needed when a name is in more than one.",
            },
            sensitive=True,
            handler=lambda name, repo="": install_skill(name, repo),
        )
    )
