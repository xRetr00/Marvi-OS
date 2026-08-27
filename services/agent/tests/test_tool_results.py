"""What the model is told a tool returned.

From a real session: asked to search the web, Marvi called `web_search`, was
handed the string "Done.", and reported "my search confirmed it" -- repeating
the 2022 answer it had already guessed. It called the tool twice and believed
the result both times.

Every result that was not a room state came back as that literal string. A tool
whose answer is discarded is worse than a tool that does not exist, because the
model believes it worked and says so with confidence.
"""

from __future__ import annotations

from marvi_agent.tools import MAX_RESULT_CHARS, describe

SEARCH = {
    "results": [
        {"title": "2026 FIFA World Cup", "snippet": "Held in North America in 2026."},
        {"title": "Winner", "snippet": "The final was played in July 2026."},
    ]
}


def test_search_results_reach_the_model() -> None:
    """The failure in one assertion."""
    said = describe(SEARCH)

    assert "2026" in said
    assert said != "Done."


def test_a_plain_string_is_passed_through() -> None:
    assert describe("the light is on") == "the light is on"


def test_a_room_state_still_reads_as_a_sentence() -> None:
    """The one result that was always rendered properly, and still is."""
    said = describe(
        {
            "live": True,
            "state": {
                "light": {"on": True, "brightness": 40},
                "modes": {"active_mode": "reading"},
                "presence": {"detected": True},
            },
        }
    )

    assert "light on at 40 percent" in said
    assert "reading" in said


def test_nothing_to_say_is_still_done() -> None:
    """A tool that succeeded and returned nothing has succeeded."""
    assert describe(None) == "Done."
    assert describe({}) == "Done."
    assert describe("") == "Done."


def test_a_long_result_is_bounded() -> None:
    """A spoken turn must not read a web page aloud."""
    said = describe({"text": "word " * 5000})

    assert len(said) <= MAX_RESULT_CHARS


def test_a_deeply_nested_result_does_not_recurse_forever() -> None:
    deep: dict = {"a": {"b": {"c": {"d": {"e": "buried"}}}}}

    describe(deep)  # must not raise or hang


def test_a_list_of_plain_values_is_readable() -> None:
    assert describe(["one", "two"]) == "one; two"


def test_a_long_listing_says_how_much_it_left_out() -> None:
    """A directory read as five dot-directories is a wrong answer, not a short one.

    From a real session: `file_list` returned 28 entries, the model was shown
    the first five -- `.claude`, `.git`, `.github`, `.playwright-cli`,
    `.pytest_cache` -- and Marvi told the user their file was not in the
    workspace and the directories looked unfamiliar. She was reporting exactly
    what she had been given.
    """
    from marvi_agent.tools import describe

    entries = [{"name": f"dir{index}", "directory": True} for index in range(20)]
    entries.append({"name": "shreef.txt", "directory": False})

    said = describe({"entries": entries})

    assert "(and 9 more)" in said


def test_a_short_listing_says_nothing_about_more() -> None:
    from marvi_agent.tools import describe

    said = describe({"entries": [{"name": "notes.md"}, {"name": "todo.md"}]})

    assert "more" not in said
    assert "notes.md" in said
