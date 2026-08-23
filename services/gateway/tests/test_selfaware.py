"""Knowing where she lives, and knowing what she can do.

Both existed on disk and neither reached the model. The skills pipeline could
browse, review, install and remove skills, and `installed()` was read by the
CLI and one API route -- so a user could install a skill and the model would
never be told it was there. And Marvi could not read her own logs at all,
which is why a broken plugin turned into a voice session spent guessing.
"""

from __future__ import annotations

import pytest

from marvi_gateway import selfaware
from marvi_gateway.setup import skills

# -- the catalogue ------------------------------------------------------------


def test_the_skills_that_ship_with_marvi_are_found_without_installing_them() -> None:
    """They live in the checkout and are read from there.

    Copying them into the user's data directory at setup would have meant a
    second copy to keep level with the first, and a skill that silently stayed
    on an old version after an update.
    """
    found = {s.name for s in skills.installed()}

    assert "diagnose-myself" in found
    assert "marvi-agent" in found


def test_every_bundled_skill_is_valid_against_the_spec() -> None:
    """Marvi's own skills go through the same parser as one off the internet."""
    for skill in skills._read_dir(skills.BUNDLED, "marvi"):
        assert skill.name and skill.description
        assert len(skill.description) <= skills.MAX_DESCRIPTION
        assert skills.NAME_PATTERN.match(skill.name), skill.name
        assert skill.body.strip(), f"{skill.name} has no instructions"
        assert not skill.problems, f"{skill.name}: {skill.problems}"


def test_the_catalogue_advertises_without_disclosing() -> None:
    """Stage one is names and descriptions. The body is the expensive part and
    it must not be in the prompt, or progressive disclosure is just disclosure.
    """
    block = skills.advertise()

    assert "diagnose-myself" in block
    assert "skill_read" in block
    # A line out of the body of one of them. If this ever appears in the
    # catalogue, every skill is being loaded on every turn.
    assert "Start here" not in block


def test_an_empty_directory_advertises_nothing() -> None:
    """An empty heading is worse than no heading: it spends tokens saying
    there is nothing to say."""
    assert skills.advertise([]) == ""


def test_a_skill_body_is_read_by_name() -> None:
    skill = skills.body_of("using-tools")

    assert skill.name == "using-tools"
    assert "Read the result before describing it" in skill.body


def test_reading_a_skill_that_is_not_there_says_what_is() -> None:
    with pytest.raises(skills.SkillError):
        skills.body_of("no-such-skill")


def test_a_users_skill_overrides_one_of_marvis(tmp_path) -> None:
    """Theirs is the later and more deliberate choice."""
    directory = tmp_path / "marvi-agent"
    directory.mkdir()
    (directory / "SKILL.md").write_text(
        "---\nname: marvi-agent\ndescription: Mine, not yours.\n---\n\nBody.\n",
        encoding="utf-8",
    )

    found = {s.name: s for s in skills.installed(tmp_path)}

    assert found["marvi-agent"].description == "Mine, not yours."
    # And the rest of the bundled set is still there.
    assert "diagnose-myself" in found


# -- reading her own logs -----------------------------------------------------


def test_a_log_name_cannot_be_talked_into_a_path(monkeypatch, tmp_path) -> None:
    """The argument is a name inside the log directory, not a path.

    This is the whole reason `marvi_logs` exists rather than pointing the
    workspace root at the installation: the workspace root that would let her
    read a log also lets her delete a model.
    """
    monkeypatch.setenv("MARVI_LOG_DIR", str(tmp_path))
    (tmp_path / "gateway.log").write_text("fine\n", encoding="utf-8")

    for attempt in ("../../secrets", r"..\..\secrets", "/etc/passwd", ".ssh"):
        answer = selfaware.read_log(attempt)
        assert answer["ok"] is False, attempt


def test_a_log_is_read_from_the_end(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MARVI_LOG_DIR", str(tmp_path))
    (tmp_path / "agent.log").write_text(
        "".join(f"line {i}\n" for i in range(100)), encoding="utf-8"
    )

    answer = selfaware.read_log("agent", lines=5)

    assert answer["ok"] is True
    assert answer["lines"] == [f"line {i}" for i in range(95, 100)]


def test_a_log_can_be_searched(monkeypatch, tmp_path) -> None:
    """Forty lines of the wrong thing is not an answer."""
    monkeypatch.setenv("MARVI_LOG_DIR", str(tmp_path))
    (tmp_path / "plugins.log").write_text(
        "loaded smart_room\nfailed to load smart_room\nloaded again\n", encoding="utf-8"
    )

    answer = selfaware.read_log("plugins", contains="FAILED")

    assert answer["matched"] == 1
    assert "failed to load" in answer["lines"][0]


def test_naming_a_log_that_is_not_there_lists_the_ones_that_are(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("MARVI_LOG_DIR", str(tmp_path))
    (tmp_path / "gateway.log").write_text("x\n", encoding="utf-8")

    answer = selfaware.read_log("nonsense")

    assert answer["ok"] is False
    assert answer["available"] == ["gateway.log"]


def test_a_huge_line_cannot_crowd_out_the_rest(monkeypatch, tmp_path) -> None:
    """LiveKit logs whole SDP offers on one line. Without a cap, one of those
    is the entire reply."""
    monkeypatch.setenv("MARVI_LOG_DIR", str(tmp_path))
    (tmp_path / "livekit.log").write_text("x" * 50_000 + "\n", encoding="utf-8")

    answer = selfaware.read_log("livekit")

    assert len(answer["lines"][0]) == selfaware.MAX_LINE_CHARS


# -- where she lives ----------------------------------------------------------


def test_the_prompt_says_where_she_is_installed() -> None:
    """Not the source repository she was built from -- the installation she is
    actually running out of, which is where her logs and plugins are."""
    from marvi_gateway import paths

    block = selfaware.situation()

    assert str(paths.root()) in block
    assert str(paths.logs_dir()) in block
    assert "marvi_logs" in block
