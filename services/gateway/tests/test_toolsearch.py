"""Finding a tool, so that having many of them stops being a problem.

Marvi has fifty-six. Their schemas are about five thousand tokens, and every
one of them was in front of the model on every turn -- including the turns that
are somebody saying good morning. Anthropic's published number is that tool
selection degrades past thirty to fifty, which is a plain mechanical account of
"most of the tools do not work" with nothing to do with which model is
answering.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from marvi_gateway.app import create_app
from marvi_gateway.toolsearch import CORE_SETTING, DEFAULT_CORE, SEARCH_TOOL, core_tools, search

CATALOGUE = [
    {
        "name": "send_email",
        "description": "Send an email from a connected account",
        "arguments": ["to", "subject", "body"],
        "input_schema": {"type": "object", "properties": {"to": {"type": "string"}}},
    },
    {
        "name": "room_set_light",
        "description": "Change the room light",
        "arguments": ["on"],
        "input_schema": {"type": "object", "properties": {"on": {"type": "boolean"}}},
    },
    {
        "name": "file_edit",
        "description": "Change part of an existing file",
        "arguments": ["path", "old", "new"],
        "input_schema": {
            "type": "object",
            "properties": {
                "old": {"type": "string", "description": "The exact text to replace"},
            },
        },
    },
    {"name": SEARCH_TOOL, "description": "Find a tool", "arguments": ["query"]},
]


# -- ranking -----------------------------------------------------------------


def test_the_obvious_search_finds_the_obvious_tool() -> None:
    assert search(CATALOGUE, "send an email")[0]["name"] == "send_email"


def test_a_name_match_beats_a_description_match() -> None:
    """A tool called `file_edit` is what somebody searching for "edit a file"
    meant, even when other descriptions mention files."""
    assert search(CATALOGUE, "edit file")[0]["name"] == "file_edit"


def test_argument_descriptions_are_searched_too() -> None:
    """That is where the words people search with often live: `file_edit` never
    says "replace", but its `old` argument does."""
    assert "file_edit" in [t["name"] for t in search(CATALOGUE, "replace")]


def test_the_search_tool_is_never_its_own_result() -> None:
    """It is already loaded, by definition, and offering it back is a step that
    leads nowhere."""
    assert SEARCH_TOOL not in [t["name"] for t in search(CATALOGUE, "find a tool")]


def test_nothing_matching_returns_nothing_rather_than_everything() -> None:
    assert search(CATALOGUE, "photosynthesis") == []


def test_a_query_of_only_filler_words_matches_nothing() -> None:
    """"how do I" ranks every tool equally, which is the same as ranking none."""
    assert search(CATALOGUE, "how do I use the") == []


def test_ties_keep_the_catalogue_order() -> None:
    """Sorting ties alphabetically led a search for "browse a website" with
    `browser_close`. Registration order reads as the sensible one."""
    family = [
        {"name": "browser_open", "description": "Open a page in the browser"},
        {"name": "browser_close", "description": "Close the page in the browser"},
    ]
    assert [t["name"] for t in search(family, "browser")] == ["browser_open", "browser_close"]


# -- the core set ------------------------------------------------------------


def test_the_search_tool_is_always_core() -> None:
    """It is the way back. Deferring it would leave nothing able to find
    anything."""
    assert SEARCH_TOOL in core_tools()


def test_the_core_set_can_be_changed_without_code(monkeypatch) -> None:
    monkeypatch.setenv(CORE_SETTING, "room_state, web_search")

    assert core_tools() == {"room_state", "web_search", SEARCH_TOOL}


def test_an_empty_setting_falls_back_to_the_default(monkeypatch) -> None:
    monkeypatch.setenv(CORE_SETTING, "   ")

    assert core_tools() == {*DEFAULT_CORE, SEARCH_TOOL}


# -- through the Gateway -----------------------------------------------------


@pytest.fixture
def client():
    with TestClient(create_app()) as made:
        yield made


def test_the_catalogue_says_which_tools_load_up_front(client) -> None:
    """Decided in one place, so voice and chat cannot drift into different
    ideas of what is always available."""
    tools = client.get("/tools").json()["tools"]
    core = {tool["name"] for tool in tools if tool["core"]}

    assert SEARCH_TOOL in core
    assert len(core) < len(tools), "deferring nothing is the problem, not the fix"


def test_searching_returns_schemas_that_can_be_called(client) -> None:
    found = client.post(
        "/tools/tool_search", json={"arguments": {"query": "email"}}
    ).json()["result"]

    assert found["tools"], "an email tool exists"
    first = found["tools"][0]
    assert first["input_schema"], "a name without its schema cannot be called"


def test_a_search_that_finds_nothing_says_how_to_search_better(client) -> None:
    """A model that gets an empty result searches again with a longer query,
    which is the opposite of what works."""
    found = client.post(
        "/tools/tool_search", json={"arguments": {"query": "zzzznothing"}}
    ).json()["result"]

    assert found["tools"] == []
    assert "one or two plain words" in found["note"].lower()
