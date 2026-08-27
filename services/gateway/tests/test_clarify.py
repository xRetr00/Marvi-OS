"""Asking the user something, without stopping the conversation.

The design decision under test is the one that is easy to get wrong: this does
not block. A tool that waits for an answer holds the turn open while the user
is trying to answer by talking -- which is a new turn, not a return value. So
the tool returns the fact that it asked, and the answer arrives the way every
other thing the user says arrives.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from marvi_gateway.app import create_app
from marvi_gateway.clarify import as_shown, bare, clean_choices, register_clarify_tool
from marvi_gateway.runtime import RuntimeStore


def asked(store: RuntimeStore, **arguments):
    """Run the tool against a real store and hand back its result."""
    registered = {}

    class Registry:
        def register(self, spec) -> None:
            registered[spec.name] = spec

    register_clarify_tool(Registry(), store)
    return registered["clarify"].handler(**arguments)


# -- the shape of a question -------------------------------------------------


def test_it_returns_immediately_rather_than_waiting(tmp_path) -> None:
    """The whole design. A blocking version holds the turn open while the user
    is trying to answer by talking."""
    store = RuntimeStore(audit_path=tmp_path / "audit.jsonl")

    result = asked(store, question="Which folder?", choices=["Marvi-OS", "Documents"])

    assert result["asked"] is True
    # No answer here, and no field pretending there might be one later.
    assert "answer" not in result


def test_the_result_tells_the_model_what_to_do_with_it(tmp_path) -> None:
    """Without this a model reads "asked: true" as the answer and carries on."""
    store = RuntimeStore(audit_path=tmp_path / "audit.jsonl")

    note = asked(store, question="Which folder?")["note"]

    assert "out loud" in note
    assert "next message" in note


def test_the_question_goes_on_the_assistant_state(tmp_path) -> None:
    store = RuntimeStore(audit_path=tmp_path / "audit.jsonl")

    asked(store, question="Which folder?", choices=["Marvi-OS"])

    assert store.assistant.question is not None
    assert store.assistant.question.text == "Which folder?"


def test_a_second_question_replaces_the_first(tmp_path) -> None:
    """Two on screen at once is a conversation that has lost track of itself,
    and the older one is always the one nobody is going to answer."""
    store = RuntimeStore(audit_path=tmp_path / "audit.jsonl")

    asked(store, question="First?")
    asked(store, question="Second?")

    assert store.assistant.question.text == "Second?"


def test_an_empty_question_is_refused(tmp_path) -> None:
    store = RuntimeStore(audit_path=tmp_path / "audit.jsonl")

    assert asked(store, question="   ")["asked"] is False
    assert store.assistant.question is None


# -- the choices -------------------------------------------------------------


def test_dict_shaped_choices_are_unwrapped() -> None:
    """Models emit these about as often as bare strings, and `str()` on one
    puts a Python repr on screen and then hands it back as the answer."""
    assert clean_choices([{"label": "Rebase"}, {"description": "Merge"}]) == ["Rebase", "Merge"]


def test_more_than_four_choices_are_cut() -> None:
    """Spoken aloud, a longer list is one nobody holds in their head."""
    assert len(clean_choices(["a", "b", "c", "d", "e", "f"])) == 4


def test_the_first_choice_is_marked_as_the_recommendation() -> None:
    assert as_shown(["Rebase", "Merge"])[0] == "Rebase (recommended)"


def test_a_lone_choice_is_not_a_recommendation() -> None:
    """There is nothing to prefer it over."""
    assert as_shown(["Rebase"]) == ["Rebase"]


def test_the_label_comes_back_off_the_answer() -> None:
    """The user pressed the decorated string; the model asked about the bare
    one, and repeating the label back out loud is nonsense."""
    assert bare("Rebase (recommended)") == "Rebase"


# -- the answer --------------------------------------------------------------


def test_answering_takes_the_card_off_screen() -> None:
    with TestClient(create_app()) as client:
        client.post("/tools/clarify", json={"arguments": {"question": "Which folder?"}})
        before = client.get("/runtime").json()["assistant"]["question"]
        assert before is not None

        after = client.post(
            "/voice/question/answer",
            json={"id": before["id"], "answer": "Marvi-OS"},
        ).json()

    assert after["assistant"]["question"] is None


def test_a_late_answer_does_not_clear_a_newer_question() -> None:
    """A press on a question that has already moved on must not take down its
    replacement."""
    with TestClient(create_app()) as client:
        client.post("/tools/clarify", json={"arguments": {"question": "First?"}})
        stale = client.get("/runtime").json()["assistant"]["question"]["id"]
        client.post("/tools/clarify", json={"arguments": {"question": "Second?"}})

        after = client.post(
            "/voice/question/answer", json={"id": stale, "answer": "yes"}
        ).json()

    assert after["assistant"]["question"]["text"] == "Second?"


def test_the_schema_the_model_sees_explains_the_arguments() -> None:
    """A spec that supplies its own schema is passed through verbatim, and the
    per-argument descriptions are never merged into it. This tool has to supply
    one -- `choices` is an array -- so carrying it silently dropped every word
    of guidance the tool was written with."""
    with TestClient(create_app()) as client:
        catalogue = client.get("/tools").json()["tools"]

    clarify = next(tool for tool in catalogue if tool["name"] == "clarify")
    properties = clarify["input_schema"]["properties"]

    assert "cannot be pressed" in properties["question"]["description"]
    assert "best first" in properties["choices"]["description"]
