"""Finding a tool, so that having many of them stops being a problem.

Marvi has fifty-six tools. Their schemas are about five thousand tokens, and
every one of them is in front of the model on every turn of every conversation
-- including the turns that are somebody saying good morning.

That is not mainly a cost problem. Anthropic's own guidance is blunt about the
accuracy: a model's ability to pick the right tool degrades once it can see
more than thirty to fifty, and the recommended remedy is to stop showing them
all. Fifty-six is past that line, which is a plain mechanical explanation for
"most of the tools do not work" that has nothing to do with which model is
answering.

## How it works here

A small core stays loaded, because a tool you use every day should not need
finding. Everything else is discovered: the model searches, gets back the
matching schemas, and can then call them for the rest of the session.

The search runs here rather than in each surface, so voice and chat rank tools
the same way and there is one place to fix when a tool turns out to be hard to
find.

## Why not the API's own tool search

The Claude API has this built in -- `defer_loading` on each tool and a
server-side search tool. Marvi's main model is whatever the user configured,
which today is DeepSeek through OpenRouter, so a feature of one provider's API
cannot be the mechanism. This is the same design implemented where every
provider can reach it: the search is an ordinary tool, and the surface adds the
tools it returns.
"""

from __future__ import annotations

import os
import re
from typing import Any

#: Tools that are always in front of the model.
#:
#: "Keep your 3-5 most frequently used tools non-deferred" is the published
#: advice; this is seven because Marvi's daily traffic is genuinely split
#: between the room, memory and looking things up, and making her search before
#: she can turn a light off would be a worse assistant to save a few hundred
#: tokens.
#:
#: `clarify` is in it for a different reason: it is what she uses when she does
#: not know something, and a tool for not knowing must not itself need finding.
DEFAULT_CORE = (
    "clarify",
    "room_state",
    "room_set_light",
    "memory_recall",
    "memory_remember",
    "web_search",
    "file_search",
)

CORE_SETTING = "MARVI_CORE_TOOLS"

#: The search itself, which can never be deferred -- it is the way back.
SEARCH_TOOL = "tool_search"

#: Words that match everything and therefore rank nothing.
STOP = frozenset(
    {
        "a", "an", "and", "any", "are", "can", "do", "does", "for", "from", "get",
        "how", "i", "in", "is", "it", "me", "my", "of", "on", "or", "that", "the",
        "then", "there", "this", "to", "tool", "tools", "use", "want", "what",
        "with", "you",
    }
)

#: A name match is worth more than a description match, which is worth more
#: than an argument match. A tool called `file_search` is what somebody
#: searching for "search files" meant, even when twenty descriptions mention
#: files.
NAME_WEIGHT = 4
DESCRIPTION_WEIGHT = 2
ARGUMENT_WEIGHT = 1
#: The whole query appearing verbatim is strong evidence and cheap to check.
PHRASE_WEIGHT = 3


def core_tools() -> set[str]:
    """The always-loaded set, which the user can change without code."""
    raw = os.environ.get(CORE_SETTING, "").strip()
    chosen = {name.strip() for name in raw.replace(";", ",").split(",") if name.strip()}
    return (chosen or set(DEFAULT_CORE)) | {SEARCH_TOOL}


def _words(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in STOP]


def _searchable(tool: dict[str, Any]) -> tuple[str, str, str]:
    """A tool's name, its description, and everything about its arguments.

    Argument names and descriptions are included because that is where the
    words people actually search with often live: `file_edit` never says
    "replace", but its `old` argument does.
    """
    schema = tool.get("input_schema")
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    arguments = " ".join(
        f"{key} {value.get('description', '') if isinstance(value, dict) else ''}"
        for key, value in properties.items()
    )
    listed = " ".join(
        str(item) for item in (*tool.get("arguments", []), *tool.get("optional", []))
    )
    return (
        str(tool.get("name") or ""),
        str(tool.get("description") or ""),
        f"{arguments} {listed}",
    )


def score(tool: dict[str, Any], query: str) -> int:
    """How well one tool answers one search. Zero means it does not."""
    name, description, arguments = _searchable(tool)
    haystacks = (name.lower(), description.lower(), arguments.lower())
    terms = _words(query)
    if not terms:
        return 0

    total = 0
    for term in terms:
        if term in haystacks[0]:
            total += NAME_WEIGHT
        if term in haystacks[1]:
            total += DESCRIPTION_WEIGHT
        if term in haystacks[2]:
            total += ARGUMENT_WEIGHT
    phrase = " ".join(terms)
    if phrase in haystacks[0].replace("_", " ") or phrase in haystacks[1]:
        total += PHRASE_WEIGHT
    return total


def search(catalogue: list[dict[str, Any]], query: str, limit: int = 5) -> list[dict[str, Any]]:
    """The best matches, best first, never more than `limit`.

    Ties keep the catalogue's own order, which is registration order and reads
    as the sensible one: a search for "browse a website" leads with
    `browser_open` rather than with `browser_close`, which is what sorting the
    ties alphabetically gave. Python's sort is stable, so this costs nothing
    and is equally repeatable -- the same search twice gives the same answer,
    which matters when the thing consuming it is a model that would otherwise
    learn two different habits.

    The search tool itself is never a result. It is already loaded, by
    definition, and offering it back is a step that leads nowhere.
    """
    ranked = [
        (score(tool, query), tool)
        for tool in catalogue
        if str(tool.get("name") or "") != SEARCH_TOOL
    ]
    hits = [entry for entry in ranked if entry[0] > 0]
    hits.sort(key=lambda entry: -entry[0])
    return [tool for _, tool in hits[: max(1, limit)]]


def register_tool_search(registry: Any, catalogue: Any) -> None:
    """`catalogue()` returns every tool description, in `/tools` shape."""
    from . import observations
    from .tools import ToolSpec

    def tool_search(query: str, limit: int = 5) -> dict[str, Any]:
        found = search(catalogue(), query, limit)
        # The one honest signal about which tools Marvi is missing. A search
        # that finds nothing is the model reaching for a capability and coming
        # back empty, and until this was recorded it reached nobody: the note
        # below goes to the model, which then works around it, and the fact
        # that it had to is gone by the next turn.
        observations.record(
            "tool",
            event="search",
            query=query,
            found=len(found),
            names=",".join(str(row.get("name")) for row in found[:3]),
        )
        if not found:
            return {
                "tools": [],
                # An empty result with advice, rather than an empty result. A
                # model that gets nothing back searches again with a longer
                # query, which is the opposite of what works.
                "note": (
                    f"Nothing matched {query!r}. Search with one or two plain "
                    "words for the thing itself -- 'light', 'email', 'file', "
                    "'screen' -- rather than a sentence."
                ),
            }
        return {
            "tools": [
                {
                    "name": tool.get("name"),
                    "description": tool.get("description"),
                    "arguments": tool.get("arguments", []),
                    "optional": tool.get("optional", []),
                    "input_schema": tool.get("input_schema", {}),
                }
                for tool in found
            ],
            "note": "These are now available to call directly.",
        }

    registry.register(
        ToolSpec(
            name=SEARCH_TOOL,
            description=(
                "Find a tool for something you cannot already do. Marvi has many "
                "more tools than the ones loaded: email, calendar, the browser, "
                "the smart room, schedules, skills, the terminal, processes, "
                "the screen"
            ),
            arguments={"query": str},
            optional={"limit": int},
            sensitive=False,
            handler=tool_search,
            describes={
                "query": "One or two plain words for the thing you need -- "
                "'email', 'browser', 'schedule', 'screen', 'light'. Names, "
                "descriptions and argument names are all searched.",
                "limit": "How many tools to return. Default 5.",
            },
        )
    )
