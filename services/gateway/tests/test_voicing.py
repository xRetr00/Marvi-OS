"""How Marvi sounds when she speaks to an empty room.

The announcer read `event["summary"]`, which is written for a journal --
`room:light_changed - light 80% (warm)`. Read aloud that is a status line, and
a status line with a voice is a dashboard, not an assistant.
"""

from __future__ import annotations

import pytest

from marvi_gateway import voicing

USER_MD = """# About the person I work for

## Name

- Shereef

## How to address them

- Shereef.
"""


def test_the_name_comes_from_the_file() -> None:
    assert voicing.name_of(USER_MD) == "Shereef"


@pytest.mark.parametrize(
    "written",
    ["- Shereef.", "- Shereef (he/him)", "* Shereef", "-   Shereef  "],
)
def test_the_name_survives_how_a_person_writes_it(written: str) -> None:
    # USER.md is a document somebody edits by hand, not a schema.
    assert voicing.name_of(f"## Name\n\n{written}\n") == "Shereef"


def test_no_name_is_a_normal_answer() -> None:
    """Every line reads correctly without one; inventing one is worse."""
    assert voicing.name_of("# About\n\nnothing here\n") == ""
    line = voicing.spoken({"source": "room", "kind": "room_welcome", "summary": "home"}, "")
    assert line and "None" not in line and "user" not in line.lower()


def test_a_light_is_something_she_did_for_you() -> None:
    line = voicing.spoken(
        {
            "source": "room",
            "kind": "light_changed",
            "summary": "light 80% (warm)",
            "payload": {"on": True, "brightness": 80},
        },
        "Shereef",
    )
    assert "Shereef" in line
    # The stance: she did it, for them. Not "the lights are now on".
    assert "I turned the lights on" in line or "lights are on" in line
    assert "light_changed" not in line and "80%" not in line


def test_a_visitor_while_you_are_out_is_not_a_pleasantry() -> None:
    """The one line where the tone has to change, and the reason for `away`."""
    event = {"source": "room", "kind": "visitor_report", "summary": "unknown face"}

    home = voicing.spoken(event, "Shereef", away=False)
    out = voicing.spoken(event, "Shereef", away=True)

    assert "not home" in out or "while you are out" in out
    assert out != home
    assert "not home" not in home


def test_nothing_known_keeps_the_gentler_reading() -> None:
    # Guessing that somebody is out and telling them there is an intruder is
    # the worse of the two mistakes.
    event = {"source": "room", "kind": "visitor_report", "summary": "unknown face"}
    assert "not home" not in voicing.spoken(event, "Shereef", away=None)


def test_trouble_says_what_it_means_for_them() -> None:
    line = voicing.spoken(
        {
            "source": "system",
            "kind": "degraded",
            "summary": "gateway unreachable",
            "payload": {"component": "gateway"},
        },
        "Shereef",
    )
    assert "Gateway connection" in line
    # Not just that something broke: what it means for the person listening.
    assert any(word in line for word in ("slower", "limited", "still here", "noticed"))


def test_an_unknown_event_is_left_alone() -> None:
    """Being unable to phrase it warmly is not a reason to invent something."""
    assert voicing.spoken({"source": "room", "kind": "mode_changed", "summary": "sleep"}) == ""


def test_the_same_event_sounds_the_same_and_different_ones_do_not() -> None:
    # Stable, so this is testable; varied, so a light switched twice in an
    # evening does not sound like a recording.
    first = {"source": "room", "kind": "light_changed", "summary": "a", "payload": {"on": True}}
    again = {"source": "room", "kind": "light_changed", "summary": "a", "payload": {"on": True}}
    assert voicing.spoken(first, "Shereef") == voicing.spoken(again, "Shereef")
    seen = {voicing.spoken({**first, "summary": str(n)}, "S") for n in range(12)}
    assert len(seen) > 1, "every light change is phrased identically"


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("room", "light_changed"),
        ("room", "visitor_report"),
        ("room", "room_welcome"),
        ("presence", "work"),
        ("presence", "left"),
        ("system", "degraded"),
    ],
)
def test_every_line_is_speakable(source: str, kind: str) -> None:
    """No markup, no ids, nothing an engine would read out as punctuation."""
    line = voicing.spoken(
        {"source": source, "kind": kind, "summary": "x", "payload": {"component": "gateway"}},
        "Shereef",
    )
    assert line
    assert line[0].isupper() and line.rstrip().endswith((".", "?"))
    for junk in ("_", "{", "}", "%", ":", "—", "None"):
        assert junk not in line, f"{junk!r} would be read aloud"
