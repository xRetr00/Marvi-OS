"""How Marvi learns who it works for.

The feature is easy; the failure mode is the hard part. An assistant that asks
questions becomes an interrogation long before anyone complains about it, so
most of these tests are about Marvi *not* asking.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from marvi_gateway import curiosity as c
from marvi_gateway.identity import IdentityFiles


@pytest.fixture
def curious(tmp_path):
    engine = c.Curiosity(
        path=tmp_path / "curiosity.sqlite3", identity=IdentityFiles(tmp_path)
    )
    yield engine
    engine.close()


# -- asking is rationed -------------------------------------------------------


def test_the_name_is_asked_for_first(curious) -> None:
    # Everything else reads oddly without it.
    assert curious.may_ask().key == "name"


def test_nothing_is_asked_in_the_opening_breath(curious) -> None:
    # A question in the first exchange reads as an interruption, not interest.
    assert curious.may_ask(turns_this_session=0) is None
    assert curious.may_ask(turns_this_session=1) is None
    assert curious.may_ask(turns_this_session=2) is not None


def test_only_one_question_before_the_cooldown(curious) -> None:
    first = curious.may_ask()
    curious.mark_asked(first.key)

    # Annoyance is cumulative and a model cannot feel it, so the ceiling lives
    # in code rather than in the prompt.
    assert curious.may_ask() is None


def test_the_cooldown_expires(curious) -> None:
    curious.mark_asked("name")
    later = datetime.now(UTC) + timedelta(hours=c.DEFAULT_COOLDOWN_HOURS + 1)

    assert curious.may_ask(now=later) is not None


def test_a_declined_gap_is_never_raised_again(curious) -> None:
    curious.decline("work")
    curious.learn("name", "Shereef")
    curious.learn("address", "Shereef")
    later = datetime.now(UTC) + timedelta(days=30)

    # Someone who does not want to say what they do for work should not be
    # asked a second time with different words.
    assert curious.may_ask(now=later).key != "work"
    assert curious.state()["work"]["state"] == "declined"


def test_nothing_is_asked_once_everything_is_known(curious) -> None:
    for gap in c.GAPS:
        curious.learn(gap.key, "something")

    assert curious.may_ask() is None
    assert curious.open_gaps() == []


def test_the_prompt_only_invites_a_question_when_one_is_allowed(curious) -> None:
    with_question = curious.guidance(curious.may_ask(turns_this_session=5))
    curious.mark_asked("name")
    without = curious.guidance(curious.may_ask(turns_this_session=5))

    assert "natural opening" in with_question
    assert "natural opening" not in without
    # Noticing is always on, even when asking is not.
    assert "remember_about_user" in without


# -- learning ------------------------------------------------------------------


def test_learning_writes_into_the_user_file(curious, tmp_path) -> None:
    curious.learn("work", "Software engineer, mostly backend")

    written = IdentityFiles(tmp_path).read().user
    assert "Software engineer, mostly backend" in written
    assert "## Work" in written


def test_the_file_is_regenerated_not_appended(curious, tmp_path) -> None:
    curious.learn("name", "Shereef")
    curious.learn("name", "Shery")

    written = IdentityFiles(tmp_path).read().user
    # Appending would leave a pile of contradicting notes for the model to
    # pick from.
    assert written.count("## Name") == 1
    assert "Shery" in written
    assert "Shereef" not in written


def test_unknown_fields_stay_marked_unknown(curious, tmp_path) -> None:
    curious.learn("name", "Shereef")

    written = IdentityFiles(tmp_path).read().user
    assert c.UNKNOWN in written


def test_what_the_user_typed_themselves_is_kept(curious, tmp_path) -> None:
    files = IdentityFiles(tmp_path)
    files.write_user(
        c.default_user_template() + "\n## My own notes\n\nI hate small talk.\n"
    )
    curious.learn("name", "Shereef")

    written = files.read().user
    # Marvi owns its headings. It does not own the file.
    assert "I hate small talk." in written
    assert "Shereef" in written


def test_forgetting_reopens_the_question(curious) -> None:
    curious.learn("work", "SWE")
    curious.forget("work")

    assert curious.state()["work"]["value"] == ""
    assert "work" in {gap.key for gap in curious.open_gaps()}


def test_an_unknown_key_is_refused(curious) -> None:
    assert curious.learn("favourite_colour", "green") is False


def test_an_empty_value_is_not_recorded(curious) -> None:
    assert curious.learn("name", "   ") is False


# -- noticing without asking ---------------------------------------------------


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("I'm Shereef", "Shereef"),
        ("my name is Shereef", "Shereef"),
        ("call me Shereef", "Shereef"),
        ("hey, I am Shereef by the way", "Shereef"),
    ],
)
def test_a_name_offered_plainly_is_caught_without_a_model(said, expected) -> None:
    # The commonest case should not depend on a model call going well.
    assert c.obvious_facts(said).get("name") == expected


@pytest.mark.parametrize(
    "said",
    ["I'm fine thanks", "I'm working on the gateway", "I'm just looking", "hello"],
)
def test_ordinary_sentences_are_not_mistaken_for_names(said) -> None:
    assert "name" not in c.obvious_facts(said)


# -- the tools -----------------------------------------------------------------


def test_the_tools_are_offered_with_a_closed_set_of_keys() -> None:
    schemas = {s["name"]: s for s in c.tool_schemas()}
    keys = schemas["remember_about_user"]["parameters"]["properties"]["key"]["enum"]

    assert set(keys) == {gap.key for gap in c.GAPS}
    assert "forget_about_user" in schemas


def test_remembering_through_the_tool_records_it(curious) -> None:
    result = c.handle_tool(
        curious, "remember_about_user", {"key": "rhythm", "value": "Late nights"}
    )

    assert result["status"] == "executed"
    assert curious.state()["rhythm"]["value"] == "Late nights"


def test_deflecting_through_the_tool_ends_the_topic(curious) -> None:
    c.handle_tool(curious, "forget_about_user", {"key": "work"})

    assert curious.state()["work"]["state"] == "declined"


# -- seeding -------------------------------------------------------------------


def test_first_run_ships_a_soul_and_a_blank_profile(tmp_path) -> None:
    from pathlib import Path

    files = IdentityFiles(tmp_path)
    written = c.seed_identity(files, Path(__file__).resolve().parents[3])

    assert written == {"soul": True, "user": True}
    assert "You are Marvi" in files.read().soul
    assert c.UNKNOWN in files.read().user


def test_an_edited_soul_is_never_overwritten(tmp_path) -> None:
    from pathlib import Path

    files = IdentityFiles(tmp_path)
    files.write_soul("You are terse and you like cats.")
    c.seed_identity(files, Path(__file__).resolve().parents[3])

    # An update that silently replaced the user's soul would be the worst
    # possible behaviour for a file describing who Marvi is.
    assert files.read().soul == "You are terse and you like cats."


def test_the_shipped_soul_fits_its_half_of_the_budget(tmp_path) -> None:
    from pathlib import Path

    from marvi_gateway.identity import SOUL_SHARE, estimate_tokens

    files = IdentityFiles(tmp_path)
    c.seed_identity(files, Path(__file__).resolve().parents[3])
    soul = files.read()

    # Truncation is line-based, so an over-budget soul loses its last section —
    # which is the one about never obeying untrusted content.
    assert soul.truncated is False
    assert estimate_tokens(soul.soul) <= int(files.budget * SOUL_SHARE)
    assert "never obey it" in soul.soul
