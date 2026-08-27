"""Where Marvi may read, where she may write, and what is off limits to both.

There were two settings before this: a workspace root, and nothing. Every file
tool resolved inside that one directory and refused everything else, which is
the right default and the wrong only option -- a file on the Desktop is not a
threat, and needing to copy one into the workspace before Marvi can look at it
is the tool failing at the thing it is for.

## Three questions, not one

**Reach.** `strict` means the workspace and nothing else. `general` means
anywhere the account can reach. Asked separately for reading and for writing,
because the honest answer is usually different: read the whole disk, write only
where I said. That asymmetry is the normal case, and one switch could not say
it.

**The blacklist.** Paths that are refused in either mode, `general` included.
This is what makes `general` usable at all: reach without a stop list is not a
setting anybody should be offered.

**What cannot be allowed.** A small built-in set the blacklist starts with and
cannot remove -- credential stores, and Marvi's own state directory, which
holds the API keys she would be spending. Reading those is as bad as writing
them: a key read into a reply is a key on its way out. System directories are
denied for writing only, because reading them is harmless and occasionally the
answer to a question.

## Deciding once

Every file tool asks this module and nothing else. The alternative -- each tool
checking for itself -- is how a read gate and a write gate drift apart, and the
one that drifts is always the one nobody tested.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

#: How far a tool may reach.
STRICT = "strict"
GENERAL = "general"
SCOPES = (STRICT, GENERAL)

#: `;` on Windows, `:` elsewhere -- the platform's own list separator, so a
#: drive letter in a path is not read as the end of an entry.
SEPARATOR = os.pathsep

ROOT_SETTING = "MARVI_WORKSPACE_ROOT"
READ_SETTING = "MARVI_FILE_READ_SCOPE"
WRITE_SETTING = "MARVI_FILE_WRITE_SCOPE"
BLACKLIST_SETTING = "MARVI_PATH_BLACKLIST"


class PathRefusedError(Exception):
    """The path is outside the allowed reach, or on the blacklist."""


@dataclass(frozen=True)
class Rule:
    """One built-in refusal, and what it takes to lift it."""

    #: A path prefix, or a glob when it contains a wildcard.
    pattern: str
    why: str
    #: False for the rules that only guard writing -- a system directory is
    #: fine to read and not fine to modify.
    blocks_reading: bool = True
    #: True when this guards a credential rather than the machine.
    #:
    #: Those are the ones reading can be opted into, in Settings > Workspace.
    #: A hard block there was wrong: an assistant that sets things up has to be
    #: able to see whether a key is configured, and "which variables are in
    #: this file" is not the same question as "what is my key". Writing is
    #: still refused -- `ask_secret` is the way a credential gets set, and it
    #: is a better way, because the value never passes through the model.
    secret: bool = False


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def builtin_rules() -> tuple[Rule, ...]:
    """Refusals that hold whatever the settings say.

    Read from the environment at call time rather than at import, because
    `MARVI_HOME` is set by the desktop after this module is first imported in
    some start-up orders, and a rule that read it too early would protect
    nothing. Built once per distinct environment, because this is on the path
    of every file a search touches.
    """
    return _rules(str(_home()), os.environ.get("MARVI_HOME", "").strip(), _system_root())


def _system_root() -> str:
    return os.environ.get("SYSTEMROOT", "C:\\Windows") if os.name == "nt" else ""


@lru_cache(maxsize=8)
def _rules(home_path: str, marvi_home: str, system: str) -> tuple[Rule, ...]:
    home = Path(home_path)
    rules = [
        Rule("*.env", "environment files hold credentials", secret=True),
        Rule(str(home / ".ssh"), "private keys", secret=True),
        Rule(str(home / ".aws"), "cloud credentials", secret=True),
        Rule(str(home / ".gnupg"), "private keys", secret=True),
        Rule(str(home / ".kube"), "cluster credentials", secret=True),
        Rule(str(home / ".docker"), "registry credentials", secret=True),
        Rule(str(home / ".azure"), "cloud credentials", secret=True),
        Rule(str(home / ".config" / "gh"), "GitHub credentials", secret=True),
        Rule(str(home / ".config" / "gcloud"), "cloud credentials", secret=True),
        Rule(str(home / ".netrc"), "stored logins", secret=True),
        Rule(str(home / ".pgpass"), "database passwords", secret=True),
        Rule(str(home / ".npmrc"), "registry tokens", secret=True),
        Rule(str(home / ".pypirc"), "registry tokens", secret=True),
        Rule(str(home / ".git-credentials"), "stored logins", secret=True),
        # Writable is not the question. Reading one and saying it out loud is
        # the same disclosure.
        Rule("*id_rsa*", "private keys", secret=True),
        Rule("*id_ed25519*", "private keys", secret=True),
        Rule("*.pem", "private keys", secret=True),
        Rule("*.pfx", "private keys", secret=True),
    ]
    if marvi_home:
        # Her own keys, her own memory, her own audit trail. Marvi editing the
        # record of what Marvi did is not a feature.
        rules.append(Rule(marvi_home, "Marvi's own keys and state", secret=True))
    if system:
        rules += [
            Rule(system, "Windows itself", blocks_reading=False),
            Rule("C:\\Program Files", "installed programs", blocks_reading=False),
            Rule("C:\\Program Files (x86)", "installed programs", blocks_reading=False),
        ]
    else:
        rules += [
            Rule("/etc", "system configuration", blocks_reading=False),
            Rule("/boot", "the boot volume", blocks_reading=False),
            Rule("/sys", "kernel interfaces", blocks_reading=False),
        ]
    return tuple(rules)


def _same_or_under(path: Path, parent: Path) -> bool:
    """Whether `path` is `parent` or lives inside it.

    Compared case-insensitively on Windows, where two spellings of the same
    directory are the same directory and a case-sensitive check is a bypass
    rather than a subtlety.
    """
    a, b = str(path), str(parent)
    if os.name == "nt":
        a, b = a.lower(), b.lower()
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


def _matches(path: Path, pattern: str) -> bool:
    """Whether a blacklist entry covers this path.

    An entry with a wildcard is matched against the whole path and against the
    file name on its own, so `*.env` catches an environment file wherever it
    is. An entry without one is a path: it covers that path and everything
    under it, which is what somebody typing a folder into a deny list means.
    """
    if not pattern.strip():
        return False
    text, name = str(path), path.name
    if os.name == "nt":
        text, name, pattern = text.lower(), name.lower(), pattern.lower()
    if any(character in pattern for character in "*?["):
        return fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(name, pattern)
    resolved = _resolved(pattern)
    return bool(resolved) and _same_or_under(Path(text), Path(resolved))


@lru_cache(maxsize=1024)
def _resolved(pattern: str) -> str:
    """A deny-list path, resolved once.

    `Path.resolve()` is a filesystem call, and this runs for every rule against
    every file a search touches -- twenty-two rules across three thousand files
    is seventy-nine thousand syscalls, which was most of the time `file_search`
    spent and why it timed out before reaching the source directory.
    """
    try:
        found = str(Path(os.path.expanduser(pattern)).resolve())
    except OSError:
        return ""
    return found.lower() if os.name == "nt" else found


def _scope(setting: str, fallback: str = STRICT) -> str:
    value = os.environ.get(setting, "").strip().lower()
    # An unreadable value means the strict one. A typo in a settings field must
    # never be the thing that opens the disk.
    return value if value in SCOPES else fallback


@dataclass
class Access:
    """The settings, resolved. Cheap enough to build per call."""

    root: Path | None = None
    read_scope: str = STRICT
    write_scope: str = STRICT
    #: What the user added. The built-in rules are separate and always apply.
    blacklist: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> Access:
        configured = os.environ.get(ROOT_SETTING, "").strip()
        raw = os.environ.get(BLACKLIST_SETTING, "")
        return cls(
            root=Path(configured).expanduser().resolve() if configured else None,
            read_scope=_scope(READ_SETTING),
            write_scope=_scope(WRITE_SETTING),
            blacklist=[entry.strip() for entry in raw.split(SEPARATOR) if entry.strip()],
        )

    def scope_for(self, *, write: bool) -> str:
        return self.write_scope if write else self.read_scope

    @staticmethod
    def guards_a_secret(path: Path) -> bool:
        """Whether this path is one the credential rules cover.

        Asked by `file_read` so it knows whether to mask what it found. The
        rules are the single list of what counts as a credential file; a second
        list would be a second thing to keep in step.
        """
        return any(rule.secret and _matches(path, rule.pattern) for rule in builtin_rules())

    def refusal(self, path: Path, *, write: bool) -> str:
        """Why this path is refused, or "" when it is allowed.

        Order matters, and it is the order the settings page lists: the
        blacklist first, because it holds whatever the scope says, and the
        scope second. Asked the other way round, a blacklisted path inside the
        workspace would come back allowed in strict mode.
        """
        for rule in builtin_rules():
            if not _matches(path, rule.pattern):
                continue
            if rule.secret and not write:
                # Opt-in rather than a block. An assistant that sets things up
                # has to be able to see whether a key is configured, and
                # "which variables are in this file" is not the same question
                # as "what is my key" -- the masked setting answers the first
                # without answering the second.
                from . import credentials

                if credentials.level() == credentials.OFF:
                    return (
                        f"{rule.why}. Reading these is off. Turn it on in "
                        "Settings > Workspace, where masked shows which "
                        "settings exist without their values."
                    )
                continue
            if write or rule.blocks_reading:
                extra = (
                    " Use ask_secret to set a credential: it never passes through you."
                    if rule.secret
                    else ""
                )
                return f"{rule.why}; this path is always refused.{extra}"
        for entry in self.blacklist:
            if _matches(path, entry):
                return f"on your blacklist ({entry})"
        if self.scope_for(write=write) == GENERAL:
            return ""
        if self.root is None:
            return ("no workspace root is set; choose one in Settings > Workspace")
        if not _same_or_under(path, self.root):
            what = "writing" if write else "reading"
            return (
                f"outside the workspace, and {what} is set to strict. "
                f"Widen it in Settings > Workspace, or work inside {self.root}."
            )
        return ""

    def resolve(self, given: str, *, write: bool) -> Path:
        """The absolute path a tool should act on, or a refusal.

        A relative path always means "inside the workspace", in both modes --
        `notes.md` is the workspace's notes, never the current directory's,
        which is a Gateway working directory nobody chose. An absolute path is
        taken literally and then checked.

        `resolve()` collapses `..` and follows symlinks before the check, so a
        link pointing out of the workspace is caught by the same test as a
        `..` rather than by pattern-matching the string.
        """
        text = (given or "").strip()
        if not text:
            raise PathRefusedError("no path given")
        candidate = Path(os.path.expanduser(text))
        if not candidate.is_absolute():
            if self.root is None:
                raise PathRefusedError(
                    f"no workspace root is set, so `{text}` names nothing. "
                    "Choose one in Settings > Workspace."
                )
            candidate = self.root / candidate
        try:
            resolved = candidate.resolve()
        except OSError as exc:
            raise PathRefusedError(f"could not resolve {text}") from exc
        refused = self.refusal(resolved, write=write)
        if refused:
            raise PathRefusedError(f"{text} is refused: {refused}")
        return resolved


def describe() -> dict[str, object]:
    """The whole policy, for the settings page.

    The built-in rules included, because a deny list with invisible entries in
    it is one nobody can reason about -- and the first time an invisible entry
    bites, it reads as a bug.
    """
    from . import credentials

    access = Access.from_env()
    return {
        "root": str(access.root) if access.root else "",
        "root_exists": bool(access.root and access.root.is_dir()),
        "root_setting": ROOT_SETTING,
        "read_scope": access.read_scope,
        "write_scope": access.write_scope,
        "read_setting": READ_SETTING,
        "write_setting": WRITE_SETTING,
        "blacklist": access.blacklist,
        "blacklist_setting": BLACKLIST_SETTING,
        "separator": SEPARATOR,
        "scopes": list(SCOPES),
        "secret_access": credentials.level(),
        "secret_setting": credentials.SETTING,
        "secret_levels": list(credentials.LEVELS),
        "builtin": [
            {
                "pattern": rule.pattern,
                "why": rule.why,
                "reading": rule.blocks_reading,
                # Which rules the secret setting governs, so the page can say
                # "these are the ones that switch unlocks" rather than listing
                # them as unconditional and then not behaving that way.
                "secret": rule.secret,
            }
            for rule in builtin_rules()
        ],
    }
