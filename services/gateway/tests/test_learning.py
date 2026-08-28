"""Writing down how to do something, after doing it once.

Memory says who the user is and what is going on; a skill
says *how to do this class of task for this user*. Corrections about how Marvi
works had nowhere to go -- memory holds facts about the world and the prompt is
fixed -- so "stop formatting like that" was forgotten by the next session,
every time.

Their strongest signal is the one nobody thinks to use: frustration. "Stop
doing that", "not like this", "I told you already" is the user teaching, and it
belongs in the skill that governs the task.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from marvi_gateway import learning
from marvi_gateway.app import create_app


class Reply:
    def __init__(self, text: str) -> None:
        self.text = text


class Model:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    def call_with_fallback(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return Reply(self.answer)


class Skill:
    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description


# -- when it fires -----------------------------------------------------------


def test_nothing_is_the_usual_answer() -> None:
    """It has to stay cheap to reach, because most turns teach nothing."""
    assert learning.propose(Model('{"act":"none"}'), "hello", "Hi.", []) == {}


def test_a_correction_about_how_she_works_becomes_a_patch() -> None:
    model = Model(
        '{"act":"patch","name":"controlling-the-room","body":"Say the brightness once.",'
        '"why":"the user asked twice not to repeat the level"}'
    )

    found = learning.propose(
        model, "stop telling me the brightness every time", "Understood.",
        [Skill("controlling-the-room", "How to check and change the room")],
    )

    assert found["act"] == "patch"
    assert found["name"] == "controlling-the-room"


def test_frustration_is_named_in_the_prompt_as_a_signal() -> None:
    """Frustration is the correction signal that otherwise disappears."""
    assert "Frustration" in learning.SYSTEM_PROMPT
    assert "stop doing that" in learning.SYSTEM_PROMPT.lower()


def test_skills_are_told_apart_from_memory_in_the_prompt() -> None:
    assert "memory, not a skill" in learning.SYSTEM_PROMPT


# -- naming, which is what stops a directory of one-off notes -----------------


def test_a_name_about_one_task_is_refused() -> None:
    """`fix-the-light-again` is a session artefact, not a class of task."""
    model = Model('{"act":"create","name":"Fix The Light Again!","body":"..."}')

    assert learning.propose(model, "x", "y", []) == {}


def test_creating_something_that_exists_becomes_a_patch() -> None:
    """Patch before create, so the skill in play is the one that improves."""
    model = Model('{"act":"create","name":"controlling-the-room","body":"...","description":"d"}')

    found = learning.propose(model, "x", "y", [Skill("controlling-the-room")])

    assert found["act"] == "patch"


def test_patching_something_absent_becomes_a_create() -> None:
    model = Model('{"act":"patch","name":"controlling-the-room","body":"..."}')

    assert learning.propose(model, "x", "y", [])["act"] == "create"


def test_the_model_is_shown_what_skills_exist() -> None:
    """It cannot prefer patching without knowing what there is to patch."""
    model = Model('{"act":"none"}')

    learning.propose(model, "x", "y", [Skill("controlling-the-room", "the room")])

    assert "controlling-the-room" in model.calls[0]["messages"][1]["content"]


# -- surviving bad answers ---------------------------------------------------


def test_an_unparseable_answer_proposes_nothing(caplog) -> None:
    assert learning.propose(Model("I think maybe yes?"), "x", "y", []) == {}


def test_no_model_proposes_nothing() -> None:
    assert learning.propose(None, "x", "y", []) == {}


def test_an_empty_body_is_refused() -> None:
    assert learning.propose(Model('{"act":"create","name":"a-good-name"}'), "x", "y", []) == {}


# -- nothing is written without a person -------------------------------------


def test_a_proposal_is_not_a_skill_until_somebody_accepts_it(tmp_path, monkeypatch) -> None:
    """A model that can write its own instructions can rewrite its own
    behaviour. The skill store settled that argument already."""
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    with TestClient(create_app()) as client:
        assert client.get("/memory/proposal").json()["proposal"] is None
        assert client.post("/memory/proposal", json={"accept": True}).status_code == 404


def test_accepting_writes_the_skill_where_skills_live(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    from marvi_gateway import paths

    with TestClient(create_app()) as client:
        client.app.state.rememberer.proposal = {
            "act": "create",
            "name": "controlling-the-room",
            "description": "How to check and change the room",
            "body": "Say the brightness once, not on every change.",
            "why": "the user asked twice",
        }
        settled = client.post("/memory/proposal", json={"accept": True}).json()

    written = paths.skills_dir() / "controlling-the-room" / "SKILL.md"
    assert settled == {"written": True, "name": "controlling-the-room", "skills": settled["skills"]}
    assert "name: controlling-the-room" in written.read_text(encoding="utf-8")
    assert "Say the brightness once" in written.read_text(encoding="utf-8")


def test_the_review_sheet_gets_what_it_needs_to_show(tmp_path, monkeypatch) -> None:
    """The desktop refuses a proposal missing its body, because the button
    under a blank sheet still writes a file."""
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    with TestClient(create_app()) as client:
        client.app.state.rememberer.proposal = {
            "act": "patch",
            "name": "controlling-the-room",
            "description": "How to check and change the room",
            "body": "Say the brightness once.",
            "why": "the user asked twice",
        }
        shown = client.get("/memory/proposal").json()["proposal"]

    assert shown["name"] and shown["body"]
    assert shown["act"] == "patch"


def test_declining_writes_nothing_and_clears_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    from marvi_gateway import paths

    with TestClient(create_app()) as client:
        client.app.state.rememberer.proposal = {
            "act": "create",
            "name": "controlling-the-room",
            "description": "d",
            "body": "b",
            "why": "w",
        }
        assert client.post("/memory/proposal", json={"accept": False}).json()["written"] is False
        # Gone, so it cannot be accepted later by somebody who did not see it.
        assert client.get("/memory/proposal").json()["proposal"] is None

    assert not (paths.skills_dir() / "controlling-the-room").exists()
