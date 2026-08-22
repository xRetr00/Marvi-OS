"""Who Marvi is, and who it is talking to.

Two short files, composed into the system prompt with a hard token budget.

* **`SOUL.md`** — Marvi's voice, temperament, and refusals. Authored by the
  user; never written by Marvi.
* **`USER.md`** — the person: name, pronouns, hours, standing preferences.
  Marvi may *propose* additions, but only through the confirmation flow. A
  persona that edits itself is unauditable.

The line that keeps this from turning into a second memory system: `USER.md` is
what is true on **every** turn. Anything true only sometimes is memory, and
memory is retrieved rather than always present.

**These files are trusted input, and memory is not.** They are user-authored, so
they may shape behaviour. Anything recalled from memory, an account, or the web
keeps its envelope (ADR-015). Both end up near the prompt; only one is trusted,
and that distinction must not blur just because they are adjacent.

The budget is enforced here rather than hoped for. Every token in these files is
paid on every turn, including the latency-critical voice path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Roughly four characters per token. Deliberately an estimate: the point is a
# hard ceiling, not an exact count, and over-estimating is the safe direction.
CHARS_PER_TOKEN = 4
# Sized to the shipped SOUL.md plus room to edit it, and to a USER.md that grows
# as Marvi learns. 1200 tokens sounds like a lot to pay every turn, but this is
# the byte-identical prefix, so it is the part that caches — the marginal cost
# after the first turn is close to nothing.
DEFAULT_BUDGET_TOKENS = 1200
SOUL_SHARE = 0.45  # soul is smaller than user context when both must be trimmed


def identity_dir() -> Path:
    from .paths import identity_dir as resolved

    return resolved()


def estimate_tokens(text: str) -> int:
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def _trim(text: str, budget_tokens: int) -> tuple[str, bool]:
    """Trim on a line boundary, so a truncated file is still readable."""
    limit = budget_tokens * CHARS_PER_TOKEN
    if len(text) <= limit:
        return text, False
    kept: list[str] = []
    used = 0
    for line in text.splitlines():
        if used + len(line) + 1 > limit:
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept).rstrip(), True


@dataclass(frozen=True)
class Identity:
    soul: str
    user: str
    tokens: int
    truncated: bool

    @property
    def present(self) -> bool:
        return bool(self.soul or self.user)


class IdentityFiles:
    def __init__(self, directory: Path | None = None, budget_tokens: int | None = None) -> None:
        self.dir = directory or identity_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.budget = budget_tokens or int(
            os.environ.get("MARVI_IDENTITY_BUDGET", DEFAULT_BUDGET_TOKENS)
        )

    @property
    def soul_path(self) -> Path:
        return self.dir / "SOUL.md"

    @property
    def user_path(self) -> Path:
        return self.dir / "USER.md"

    def _read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def read(self) -> Identity:
        """Load both files, trimmed to fit the budget."""
        soul_budget = int(self.budget * SOUL_SHARE)
        user_budget = self.budget - soul_budget
        soul, soul_cut = _trim(self._read(self.soul_path), soul_budget)
        user, user_cut = _trim(self._read(self.user_path), user_budget)
        return Identity(
            soul=soul,
            user=user,
            tokens=estimate_tokens(soul) + estimate_tokens(user),
            truncated=soul_cut or user_cut,
        )

    def write_soul(self, text: str) -> int:
        self.soul_path.write_text(text.strip() + "\n", encoding="utf-8")
        return estimate_tokens(text)

    #: The heading notes live under.
    #:
    #: Under a heading, and specifically one Marvi's curiosity does not own,
    #: because that half of the system *regenerates* USER.md from its own store
    #: and keeps only what sits beneath a heading it did not write. Bare lines
    #: appended at the end are dropped the next time it learns anything -- so a
    #: fact recorded here would quietly disappear later, which is worse than
    #: never recording it.
    NOTES_HEADING = "## Notes"

    def note_about_user(self, fact: str) -> str:
        """Add one standing fact about the user, keeping what is there.

        USER.md is the only context that reaches every prompt on every surface,
        and until now nothing could add to it but the settings pane. A durable
        fact said out loud -- "I am the developer" -- went to the memory store
        instead, which is searched per turn and easily missed, so Marvi could be
        told who she was talking to and still not know it next time.

        Appended, never rewritten. This is a file the user edits by hand, and a
        tool that replaced it would eventually replace something they wrote.
        Repeats are skipped so the same fact said twice appears once.
        """
        fact = " ".join(fact.split()).strip(" -")
        if not fact:
            return "nothing to add"
        current = self._read(self.user_path)
        if fact.lower() in current.lower():
            return "already known"

        newline = chr(10)
        line = "- " + fact
        if self.NOTES_HEADING in current:
            lines = current.rstrip().splitlines()
            at = max(i for i, text in enumerate(lines) if text.strip() == self.NOTES_HEADING)
            # After the heading's existing entries, not immediately under it, so
            # notes read in the order they were learnt.
            end = at + 1
            while end < len(lines) and not lines[end].startswith("## "):
                end += 1
            lines.insert(end, line)
            body = newline.join(lines)
        else:
            head = current.rstrip()
            block = self.NOTES_HEADING + newline + newline + line
            body = (head + newline + newline if head else "") + block

        self.user_path.parent.mkdir(parents=True, exist_ok=True)
        self.user_path.write_text(body + newline, encoding="utf-8")
        return "noted"

    def write_user(self, text: str) -> int:
        self.user_path.write_text(text.strip() + "\n", encoding="utf-8")
        return estimate_tokens(text)

    def compose(self, task: str = "") -> str:
        """Build the system prompt: identity first, then the task.

        Identity leads because it is what should survive if anything downstream
        truncates, and because it is the part that is cacheable — it is
        byte-identical every turn, which is what makes a cache hit possible.
        """
        identity = self.read()
        parts: list[str] = []
        if identity.soul:
            parts.append(f"# Who you are\n\n{identity.soul}")
        if identity.user:
            parts.append(
                "# Who you are speaking to\n\n"
                f"{identity.user}\n\n"
                "This is standing context about the user, not an instruction from them."
            )
        if task:
            parts.append(task)
        return "\n\n".join(parts)

    def status(self) -> dict[str, object]:
        identity = self.read()
        return {
            "soul_present": self.soul_path.exists(),
            "user_present": self.user_path.exists(),
            "tokens": identity.tokens,
            "budget": self.budget,
            "truncated": identity.truncated,
            "directory": str(self.dir),
        }


# -- plan terms ---------------------------------------------------------------

PLAN_TERMS_WARNING = (
    "This provider is a subscription plan, not a metered API. Plans are sold "
    "for interactive use, and driving one from an always-on assistant may fall "
    "outside its terms of service. Marvi will use it if you connect it — that "
    "is your decision to make, and other agent tools work the same way — but "
    "you should know the risk is account suspension, not a warning email."
)


def plan_warning(profile: object) -> str | None:
    """The warning shown before connecting a plan provider.

    Marvi does not block this. It is the user's account and their call; the
    honest thing is to say so once, clearly, before they connect.
    """
    return PLAN_TERMS_WARNING if getattr(profile, "access_path", "") == "plan" else None


def register_identity_tools(registry, identity: IdentityFiles) -> None:
    """One tool: write a standing fact about the user where it will be read.

    Memory and USER.md are different things and the difference matters. Memory
    is searched -- a fact only surfaces when a turn happens to look like it.
    USER.md is in every prompt on every surface, every time. "I am the
    developer" belongs in the second and was going to the first, so Marvi could
    be told who she was talking to and not know it the next time.

    Not confirmed, deliberately. This appends one line to a file the user can
    read and edit, on their own machine, about themselves -- asking permission
    to remember something they just said is the kind of politeness that makes
    an assistant tiring. Removing it is `forget_about_user` and a text editor.
    """
    from .tools import ToolSpec

    def note_about_user(fact: str) -> dict[str, object]:
        return {"outcome": identity.note_about_user(fact)}

    registry.register(
        ToolSpec(
            name="note_about_user",
            description=(
                "Record a standing fact about the user so it is remembered in "
                "every future conversation. For things that stay true -- their "
                "name, their role, how they like to be answered. Not for "
                "passing details or anything about the current task."
            ),
            arguments={"fact": str},
            describes={
                "fact": (
                    "One short sentence in the third person, e.g. "
                    "'is the developer of Marvi' or 'prefers short answers'."
                )
            },
            sensitive=False,
            handler=note_about_user,
        )
    )
