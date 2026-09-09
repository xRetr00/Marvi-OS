"""Every prompt Marvi sends, as a named file rather than a string in a module.

Nineteen prompt constants were spread across seventeen modules -- `chat.py`,
`remembering.py`, `dreaming.py`, `gatekeeping.py`, `deliberate.py`, and on --
about twenty-one thousand characters of instruction with no index. Changing how
Marvi behaves meant knowing which module owned the sentence, and the cost of
not knowing was not theoretical: the background mind read "Silence is the
normal, correct answer" out of `deliberate.SYSTEM_PROMPT` while the persona
file said the opposite, and it took a session of measurement to find the
string.

The structure here is Claude Code's, which solves the same problem at a larger
scale -- 515 named prompt strings, each with a name, a description and a
declared set of variables, extracted and tracked individually rather than
assembled by hand. See `docs/prompt-registry.md`.

A prompt is a file:

    <!--
    name: "Mind: deciding what to say"
    description: "What the background mind is deciding and what it may skip."
    variables:
      - "STANCE"
    -->
    You decide whether a background event is worth telling someone about...
    ${STANCE}

Three properties, and each one is a bug that has actually happened:

* **Named.** You can find it. `prompts.catalogue()` lists every one with its
  size, so nobody has to grep for a sentence they half remember.
* **Declared variables.** A prompt says what it interpolates, and passing the
  wrong set is an error rather than a `${STANCE}` shipped verbatim to a model.
* **Measured.** Sizes are reported, so prompt growth is visible before it is
  expensive. The Agent's instruction block reached seventeen thousand
  characters without anyone deciding it should.

What does *not* live here: character. How Marvi talks belongs to
`config/personas`, and the split is the point -- a persona is a choice the user
makes, a prompt is the job it is doing. See `personas.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

#: Where the prompt files live, relative to the repository root.
FOLDER = "prompts"

#: The frontmatter block, in the same shape Claude Code's extracted prompts
#: use: an HTML comment, so a prompt file renders as plain Markdown anywhere
#: and the metadata does not reach the model.
FRONT = re.compile(r"\A<!--\n(?P<meta>.*?)\n-->\n?(?P<body>.*)\Z", re.S)

#: The one thing a prompt body may interpolate. Nothing else is special --
#: see `Prompt.render`.
SLOT = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)\}")

#: Roughly four characters to a token. Not exact, and not meant to be -- it is
#: for noticing that something doubled, not for billing.
CHARS_PER_TOKEN = 4


class PromptError(Exception):
    """A prompt is missing, malformed, or asked for with the wrong variables."""


@dataclass(frozen=True)
class Prompt:
    """One prompt file."""

    key: str
    name: str
    description: str
    variables: tuple[str, ...]
    body: str
    #: When a sub-agent carrying this prompt should be chosen. Empty for the
    #: prompts that are not agents.
    #:
    #: Claude Code declares this next to the prompt rather than in the code
    #: that dispatches -- `agentMetadata.whenToUse` -- so the description a
    #: router reads and the instructions the agent receives cannot drift.
    #: Marvi has no sub-agent system yet; `coding-agent` is delegated to an
    #: outside CLI today. Declaring it here means the day that changes, the
    #: routing information is already written and already reviewed.
    when_to_use: str = ""
    #: Tools a sub-agent carrying this prompt must not be given.
    #:
    #: A request, not an enforcement -- exactly as in `skills`. It never widens
    #: anything, and the runtime is what actually withholds a tool.
    denied_tools: tuple[str, ...] = ()

    @property
    def is_agent(self) -> bool:
        return bool(self.when_to_use)

    @property
    def chars(self) -> int:
        return len(self.body)

    @property
    def tokens(self) -> int:
        """Approximate. See `CHARS_PER_TOKEN`."""
        return round(self.chars / CHARS_PER_TOKEN)

    def render(self, **values: object) -> str:
        """Fill the declared variables. Every one, and only those.

        Both directions are errors on purpose. A missing value used to reach
        the model as the literal text `${STANCE}`, which reads to it as an
        instruction it cannot follow; an extra one is a rename that got half
        way, and silently doing nothing is how the other half stays lost.
        """
        given = set(values)
        declared = set(self.variables)
        if missing := declared - given:
            raise PromptError(f"{self.key} needs {', '.join(sorted(missing))}")
        if extra := given - declared:
            raise PromptError(f"{self.key} does not use {', '.join(sorted(extra))}")
        if not declared:
            return self.body
        # Substituted by hand rather than with `string.Template`, whose `$$`
        # means a literal `$`. The chat prompt tells the model to write maths
        # as LaTeX "inside $...$ or $$...$$ delimiters", and Template quietly
        # turned that into "$...$ or $...$" -- the instruction losing the half
        # it was there to give. Only `${NAME}` is special here; every other
        # dollar in a prompt is prose.
        return SLOT.sub(lambda hit: str(values[hit["name"]]), self.body)


def _folder(root: Path | None = None) -> Path:
    """The repository's prompts, found the way personas are found."""
    if root is not None:
        return root / FOLDER
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / FOLDER).is_dir():
            return parent / FOLDER
    return here.parent / FOLDER


def _parse(key: str, text: str) -> Prompt:
    matched = FRONT.match(text)
    if not matched:
        raise PromptError(f"{key} has no frontmatter comment")
    meta: dict[str, str] = {}
    lists: dict[str, list[str]] = {"variables": [], "denied-tools": []}
    listing = ""
    for raw in matched["meta"].splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("- "):
            if listing in lists:
                lists[listing].append(line[2:].strip().strip("\"'"))
            continue
        field, sep, value = line.partition(":")
        if not sep:
            continue
        listing = field.strip()
        if value.strip():
            meta[listing] = value.strip().strip("\"'")
    body = matched["body"].strip()
    if not body:
        raise PromptError(f"{key} has no body")
    if not meta.get("description"):
        # The description is what makes a registry a registry rather than a
        # directory. Without it the next person still has to open every file.
        raise PromptError(f"{key} needs a description")
    return Prompt(
        key=key,
        name=meta.get("name", key),
        description=meta["description"],
        variables=tuple(lists["variables"]),
        body=body,
        when_to_use=meta.get("when-to-use", ""),
        denied_tools=tuple(lists["denied-tools"]),
    )


@cache
def _load(folder: str) -> dict[str, Prompt]:
    found: dict[str, Prompt] = {}
    for path in sorted(Path(folder).glob("*.md")):
        found[path.stem] = _parse(path.stem, path.read_text(encoding="utf-8"))
    return found


def catalogue(root: Path | None = None) -> list[Prompt]:
    """Every prompt, largest first. What the inventory is for."""
    return sorted(_load(str(_folder(root))).values(), key=lambda one: -one.chars)


def agents(root: Path | None = None) -> list[Prompt]:
    """The prompts that describe a sub-agent, for whatever routes to them."""
    return [one for one in catalogue(root) if one.is_agent]


def get(key: str, root: Path | None = None) -> Prompt:
    known = _load(str(_folder(root)))
    if key not in known:
        raise PromptError(f"no prompt called {key!r}; have {', '.join(sorted(known))}")
    return known[key]


def text(key: str, root: Path | None = None, **values: object) -> str:
    """The prompt, ready to send."""
    return get(key, root).render(**values)


def forget() -> None:
    """Drop the cache. For tests, and for editing a prompt while running."""
    _load.cache_clear()
