"""Installing skills.

A skill is a directory with a `SKILL.md` in it, following the Agent Skills
specification: YAML frontmatter with `name` and `description`, optional
`license`, `compatibility`, `metadata` and `allowed-tools`, then Markdown
instructions, with optional `scripts/`, `references/` and `assets/`. Marvi
implements that format rather than a private one, so a skill written for any
other agent works here and one written here works elsewhere.

## `allowed-tools` is a request, never a grant

This is the line that matters. A skill's frontmatter can name the tools it wants
pre-approved, and the obvious reading — "the skill lists it, so the skill gets
it" — would mean **any skill can grant itself anything by editing a text file**.
A skill that arrives saying `allowed-tools: send_email` would be authorised to
send email without asking, from a file the user very likely did not read.

So the declaration is intersected with what Marvi already permits and never
widens it. A sensitive tool stays sensitive. What `allowed-tools` actually buys
is the opposite of privilege: it *narrows* the skill to the tools it says it
needs, which is useful, and is the only direction that is safe.

## The body is instructions, not data

A skill's Markdown legitimately shapes behaviour — that is its purpose, and
wrapping it in an untrusted envelope would make it useless. That is precisely
why installing one is a decision the user makes explicitly about a source they
named, and why the body is shown before it is installed.

## Scripts are not run at install time

`scripts/` may contain executables. Nothing here executes them; they run only
when the agent decides to, through the same tool boundary as anything else.
Installing a skill must never be a way to run code.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..logs import get_logger
from ..paths import skills_dir
from . import skill_guard

log = get_logger("setup")

SKILL_FILE = "SKILL.md"
#: From the specification: 1-64 chars, lowercase alphanumeric and hyphens, no
#: leading, trailing or consecutive hyphens.
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
#: The spec recommends keeping the body small because it is loaded whole on
#: activation. Warned about, not enforced — it is the author's call.
RECOMMENDED_BODY_LINES = 500

ALLOWED_SUBDIRECTORIES = {"scripts", "references", "assets"}


@dataclass
class Skill:
    name: str
    description: str
    license: str = ""
    compatibility: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    #: What the skill asks for. Intersected with policy, never applied as given.
    requested_tools: tuple[str, ...] = ()
    body: str = ""
    source: str = ""
    path: Path | None = None
    #: Spec violations that are worth saying but not worth refusing over.
    problems: tuple[str, ...] = ()
    #: Which platforms this is for. Empty means all of them.
    platforms: tuple[str, ...] = ()
    #: Settings that must be present for this skill to be any use. A skill for
    #: a service Marvi has no credential for is a line in every prompt for a
    #: thing she cannot do -- and on voice that line is latency you can hear.
    requires: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "license": self.license,
            "compatibility": self.compatibility,
            "metadata": self.metadata,
            "requested_tools": list(self.requested_tools),
            "source": self.source,
            "problems": list(self.problems),
            "platforms": list(self.platforms),
            "requires": list(self.requires),
            "applies": self.applies(),
            "installed_at": str(self.path) if self.path else "",
        }


    def applies(self) -> bool:
        """Whether this skill is any use on this machine, right now.

        Two conditions govern the same cost: a skill's name and description sit
        in the prompt on every turn. One for a
        platform you are not on, or for a service with no credential
        configured, is a line spent advertising something that cannot happen.
        """
        import os
        import sys

        if self.platforms and not any(
            sys.platform.startswith(PLATFORMS.get(name.strip().lower(), name.strip().lower()))
            for name in self.platforms
        ):
            return False
        return all(os.environ.get(name.strip(), "").strip() for name in self.requires if name.strip())


#: What a skill author writes, and what Python calls it.
PLATFORMS = {"windows": "win32", "macos": "darwin", "mac": "darwin", "linux": "linux"}


class SkillError(Exception):
    pass


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Read the YAML block between the leading `---` markers.

    Deliberately a small parser rather than a YAML dependency: the spec's
    frontmatter is flat scalars plus one optional one-level map, and a full YAML
    loader on a file from the internet is a larger surface than the feature
    needs.
    """
    if not text.startswith("---"):
        raise SkillError("SKILL.md must start with YAML frontmatter")
    end = text.find("\n---", 3)
    if end == -1:
        raise SkillError("the frontmatter block is not closed")
    block, body = text[3:end], text[end + 4 :]

    data: dict[str, Any] = {}
    current_map: str | None = None
    block_key: str | None = None
    block_lines: list[str] = []
    folded = False

    def close_block() -> None:
        nonlocal block_key, block_lines
        if block_key is not None:
            separator = " " if folded else "\n"
            data[block_key] = separator.join(
                line.strip() for line in block_lines
            ).strip()
            block_key, block_lines = None, []

    for raw in block.splitlines():
        # Block scalars are common in real skills. A parser that ignores them
        # shows a literal "|-" where the description should be.
        if block_key is not None:
            if raw.startswith((" ", "\t")) or not raw.strip():
                block_lines.append(raw)
                continue
            close_block()

        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith((" ", "\t")) and current_map:
            key, _, value = raw.strip().partition(":")
            if key:
                data.setdefault(current_map, {})[key.strip()] = value.strip().strip("\"'")
            continue
        key, separator, value = raw.partition(":")
        if not separator:
            continue
        key, value = key.strip(), value.strip()
        if value.startswith(("|", ">")):
            block_key, block_lines, current_map = key, [], None
            folded = value.startswith(">")
            continue
        value = value.strip("\"'")
        if value:
            data[key] = value
            current_map = None
        else:
            data[key] = {}
            current_map = key
    close_block()
    return data, body.lstrip("\n")


def parse(text: str, source: str = "") -> Skill:
    data, body = _parse_frontmatter(text)

    name = str(data.get("name", "")).strip()
    if not name:
        raise SkillError("frontmatter is missing `name`")
    if len(name) > MAX_NAME or not NAME_PATTERN.match(name):
        raise SkillError(
            f"`{name}` is not a valid skill name: lowercase letters, digits and "
            "single hyphens only, up to 64 characters"
        )
    description = str(data.get("description", "")).strip()
    if not description:
        raise SkillError("frontmatter is missing `description`")
    # Over-length is a quality problem, not a broken file. Anthropic's own
    # `claude-api` skill exceeds the 1024-character limit, and a store that
    # silently hides real skills for it would be worse than one that shows them
    # with a note. Structural rules stay hard errors; these are soft.
    compatibility = str(data.get("compatibility", "")).strip()

    def listed(key: str) -> tuple[str, ...]:
        raw = data.get(key, "")
        if isinstance(raw, list):
            return tuple(str(item).strip() for item in raw if str(item).strip())
        # `platforms: windows, linux` and `platforms: [windows, linux]` are
        # both what people write, and neither is worth rejecting a skill over.
        return tuple(
            part.strip() for part in str(raw).strip("[]").replace(",", " ").split() if part.strip()
        )

    raw_tools = data.get("allowed-tools", "")
    requested = tuple(t for t in str(raw_tools).split() if t) if raw_tools else ()
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}

    problems: list[str] = []
    if len(description) > MAX_DESCRIPTION:
        problems.append(
            f"`description` is {len(description)} characters; the specification "
            "recommends 1024 or fewer, and it is loaded for every skill at startup"
        )
    if len(compatibility) > MAX_COMPATIBILITY:
        problems.append("`compatibility` is longer than 500 characters")

    return Skill(
        name=name,
        description=description,
        problems=tuple(problems),
        license=str(data.get("license", "")).strip(),
        compatibility=compatibility,
        metadata={str(k): str(v) for k, v in (metadata or {}).items()},
        requested_tools=requested,
        platforms=listed("platforms"),
        requires=listed("requires"),
        body=body,
        source=source,
    )


def read_skill(directory: Path) -> Skill:
    path = directory / SKILL_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillError(f"cannot read {path}: {exc}") from exc
    skill = parse(text, source=str(directory))
    if skill.name != directory.name:
        # The spec requires it, and a mismatch is how one skill quietly
        # overwrites another on install.
        raise SkillError(
            f"the skill is named `{skill.name}` but its folder is `{directory.name}`"
        )
    skill.path = directory
    return skill


# -- what a skill is allowed to do -------------------------------------------------


#: Sources whose skills get the benefit of the doubt, comma separated. A
#: repository prefix is enough -- trusting `github.com/anthropics/skills` covers
#: everything in it without listing each one.
TRUSTED_SOURCES_SETTING = "MARVI_SKILL_TRUSTED_SOURCES"


def trusted_sources() -> tuple[str, ...]:
    import os

    raw = os.environ.get(TRUSTED_SOURCES_SETTING, "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def permitted_tools(skill: Skill, registry: Any) -> dict[str, Any]:
    """Resolve `allowed-tools` against what Marvi actually permits.

    Intersection only. A skill naming a tool that does not exist gets nothing
    for it, and a skill naming a sensitive tool does not thereby make it
    unsensitive — it still goes through confirmation.
    """
    known = {spec.name: spec for spec in registry}
    if not skill.requested_tools:
        # No declaration means the normal tool set, not "everything unlocked".
        return {"tools": sorted(known), "narrowed": False, "unknown": [], "still_sensitive": []}

    requested = {t.split("(")[0] for t in skill.requested_tools}
    granted = sorted(requested & set(known))
    unknown = sorted(requested - set(known))
    return {
        "tools": granted,
        "narrowed": True,
        "unknown": unknown,
        # Named explicitly so the install screen can say it out loud: listing a
        # sensitive tool does not pre-approve it.
        "still_sensitive": sorted(n for n in granted if known[n].sensitive),
    }


def review(skill: Skill, registry: Any = None) -> dict[str, Any]:
    """Everything the user should see before installing. Writes nothing."""
    warnings: list[str] = []
    lines = skill.body.count("\n") + 1
    if lines > RECOMMENDED_BODY_LINES:
        warnings.append(
            f"The instructions are {lines} lines; the specification recommends "
            "under 500, since the whole body loads when the skill activates."
        )
    if skill.requested_tools:
        warnings.append(
            "This skill names tools it wants: "
            + ", ".join(skill.requested_tools)
            + ". Marvi treats that as a request, never a grant — sensitive "
            "actions still ask you first."
        )
    result = {
        "skill": skill.as_dict(),
        # Shown, not summarised: it is instructions that will shape behaviour.
        "instructions": skill.body,
        "warnings": warnings,
        # Read before Marvi reads it. The body was previously shown on screen
        # with an Install button under it, and "you were shown it" is not a
        # control -- nobody reads five hundred lines before clicking.
        "scan": skill_guard.verdict(skill.body, skill.source, trusted_sources()),
    }
    if registry is not None:
        result["tools"] = permitted_tools(skill, registry)
    return result


# -- installing -----------------------------------------------------------------------


#: Skills that ship with Marvi, in the checkout rather than in the user's data
#: directory. They are read from where they live instead of copied into place:
#: nothing to install, nothing to drift, and they update when Marvi does.
BUNDLED = Path(__file__).resolve().parents[5] / "skills"


def _read_dir(base: Path, source: str) -> list[Skill]:
    found: list[Skill] = []
    if not base.exists():
        if base == BUNDLED:
            # Marvi's own skills are part of the product, so their absence is a
            # packaging fault rather than a configuration choice -- and it
            # would otherwise look exactly like having no skills, which is the
            # kind of silent nothing that costs an afternoon to find.
            log.warning("the skills that ship with Marvi are missing from %s", base)
        return found
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        try:
            skill = read_skill(child)
            skill.source = skill.source or source
            found.append(skill)
        except SkillError as exc:
            log.warning("skipping skill in %s: %s", child.name, exc)
    return found


def installed(directory: Path | None = None) -> list[Skill]:
    """Every skill Marvi can use: the ones that ship with her, then the ones
    the user installed. A user's skill of the same name wins, because it is the
    later and more deliberate choice.
    """
    by_name = {s.name: s for s in _read_dir(BUNDLED, "marvi")}
    for skill in _read_dir(directory or skills_dir(), "installed"):
        by_name[skill.name] = skill
    return [by_name[name] for name in sorted(by_name)]


def advertise(available: list[Skill] | None = None) -> str:
    """Stage one of progressive disclosure: what exists, not how to do it.

    The spec puts `name` and `description` in the prompt at startup and the
    body behind a deliberate read, at roughly a hundred tokens advertised
    against several thousand loaded. That ratio is the whole point, and it is
    why this is a list of one-liners rather than a concatenation of the files:
    a skill nobody uses this turn should cost a sentence, not a page.

    Marvi answers by voice, where an unused paragraph is not just tokens but
    latency on every single turn.
    """
    rows = available if available is not None else installed()
    # Skills that cannot run here are not advertised. Not filtered out of the
    # store or the page -- they exist and the user should see them -- only kept
    # out of the prompt, where every line is paid for on every turn.
    rows = [skill for skill in rows if skill.applies()]
    if not rows:
        return ""
    lines = [f"- {skill.name}: {skill.description}" for skill in rows]
    nl = chr(10)
    return (
        "# Skills you can use"
        + nl
        + nl
        + nl.join(lines)
        + nl
        + nl
        + "You already have these. They are procedures written down so you do "
        "not have to work them out again: when one matches what you are "
        "doing, call `skill_read` with its name to get the instructions, then "
        "follow them. Only the names and descriptions are here; the "
        "instructions are not, which is why reading one is a tool call."
        + nl
        + nl
        + "If you are asked what you can do, this list is the answer. "
        "`skill_find` searches a store of skills you could install as well as "
        "these; a store entry saying \"not installed\" says nothing about the "
        "ones above."
    )


def body_of(name: str, directory: Path | None = None) -> Skill:
    """Stage two: one skill's instructions, read when it is chosen."""
    for skill in installed(directory):
        if skill.name == name:
            return skill
    raise SkillError(f"no skill named {name!r}")


def install_from(source: Path, directory: Path | None = None) -> dict[str, Any]:
    """Copy a skill directory into place after validating it."""
    base = directory or skills_dir()
    try:
        skill = read_skill(source)
    except SkillError as exc:
        return {"ok": False, "detail": str(exc)}

    destination = base / skill.name
    base.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    copied = 0
    for item in source.iterdir():
        if item.name == SKILL_FILE:
            shutil.copy2(item, destination / SKILL_FILE)
            copied += 1
        elif item.is_dir() and item.name in ALLOWED_SUBDIRECTORIES:
            shutil.copytree(item, destination / item.name)
            copied += 1
        elif item.is_file():
            shutil.copy2(item, destination / item.name)
            copied += 1
        # Anything else — an unexpected directory — is left behind rather than
        # copied. A skill is SKILL.md plus three known folders.

    log.info("installed skill %s", skill.name, extra={"marvi_source": str(source)})
    return {"ok": True, "detail": f"installed {skill.name}", "items": copied}


def remove(name: str, directory: Path | None = None) -> dict[str, Any]:
    base = directory or skills_dir()
    target = base / name
    try:
        resolved = target.resolve()
    except OSError:
        return {"ok": False, "detail": "could not resolve that path"}
    if base.resolve() not in resolved.parents:
        # A name like `../../something` must not delete outside the skills tree.
        return {"ok": False, "detail": "refusing to remove a path outside skills"}
    if not resolved.exists():
        return {"ok": False, "detail": f"no skill named {name}"}
    shutil.rmtree(resolved)
    log.info("removed skill %s", name)
    return {"ok": True, "detail": f"removed {name}"}
