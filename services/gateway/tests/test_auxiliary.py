"""Which model does which job.

The interesting properties are not "does a setting round-trip". They are:
does an unset role change anything, does a typo stop Marvi thinking, and can a
role hand the voice path a provider it cannot call.
"""

from __future__ import annotations

from marvi_gateway import auxiliary


def test_an_unset_role_changes_nothing(monkeypatch) -> None:
    """Auto is the default and it is what happened before this existed. A role
    nobody has touched must add no argument to the call."""
    for role in auxiliary.ROLES:
        monkeypatch.delenv(role.setting, raising=False)

    assert auxiliary.overrides("mind") == {}
    assert auxiliary.resolve("voice") == ("", "")


def test_a_role_names_a_provider_and_a_model(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_AUX_MIND", "openrouter/deepseek/deepseek-v4-flash-0731")

    assert auxiliary.overrides("mind") == {
        "provider": "openrouter",
        # The model may contain the separator; only the first one splits.
        "model": "deepseek/deepseek-v4-flash-0731",
    }


def test_a_typo_falls_back_rather_than_raising(monkeypatch) -> None:
    """This sits on the path of every background call. A malformed settings
    field must not be able to stop the mind."""
    for bad in ("nonsense", "openrouter/", "/a-model", "   "):
        monkeypatch.setenv("MARVI_AUX_MIND", bad)
        assert auxiliary.overrides("mind") == {}, bad


def test_every_offered_role_has_a_call_site() -> None:
    """A setting for a call that is never made reads as a knob, does nothing,
    and teaches people the page is decorative.

    Memory, web reading and titles were held back for exactly that reason and
    arrived with their calls: reflection now has a summariser, `web_extract`
    takes a question, and a thread is named by a model rather than by
    truncating at fifty-two characters. This asserts the rule rather than the
    list, so a role added without a caller fails here.
    """
    import inspect
    from pathlib import Path

    from marvi_gateway import chat, deliberate, distil, memory, web

    sources = chr(10).join(
        inspect.getsource(module) for module in (chat, deliberate, distil, memory, web)
    )
    sources += (
        Path(inspect.getfile(auxiliary)).with_name("app.py").read_text(encoding="utf-8")
    )

    for role in auxiliary.ROLES:
        assert f'"{role.key}"' in sources, f"{role.key} is offered and nothing calls it"

    assert auxiliary.NOT_YET == ()


def test_an_unknown_role_is_auto_rather_than_an_error() -> None:
    assert auxiliary.overrides("no-such-role") == {}


def test_the_status_says_what_each_role_resolves_to(monkeypatch) -> None:
    monkeypatch.delenv("MARVI_AUX_VOICE", raising=False)
    monkeypatch.setenv("MARVI_AUX_MIND", "openai/gpt-5-mini")

    rows = {row["key"]: row for row in auxiliary.status()["roles"]}

    assert rows["voice"]["auto"] is True
    assert rows["mind"]["auto"] is False
    assert rows["mind"]["model"] == "gpt-5-mini"
    assert rows["mind"]["setting"] == "MARVI_AUX_MIND"


# -- the three that arrived with their call sites -----------------------------


def test_a_title_falls_back_to_the_truncation() -> None:
    """Nobody waits for a title, so it is the cheapest place to spend a model
    and the safest place to lose one. No client means the old behaviour."""
    from marvi_gateway import distil

    assert distil.title(None, "a long first message", "a long first…") == "a long first…"


def test_a_model_that_ignores_the_instruction_loses_to_the_truncation() -> None:
    """A paragraph is a worse title than a truncation, so the truncation wins."""
    from marvi_gateway import distil

    class Rambling:
        def call_with_fallback(self, *_a, **_k):
            class Answer:
                text = "Certainly! Here is a title for your conversation: " + "x" * 200

            return Answer()

    assert distil.title(Rambling(), "hello", "hello") == "hello"


def test_a_title_is_stripped_of_the_punctuation_models_add() -> None:
    from marvi_gateway import distil

    class Quoting:
        def call_with_fallback(self, *_a, **_k):
            class Answer:
                text = '"Kokoro voice latency."'

            return Answer()

    assert distil.title(Quoting(), "hello", "hello") == "Kokoro voice latency"


def test_memory_consolidation_only_keeps_subjects_that_were_asked_about() -> None:
    """A model inventing a subject would write a fact about nothing into
    somebody's memory."""
    from marvi_gateway import distil

    class Inventing:
        def call_with_fallback(self, *_a, **_k):
            class Answer:
                text = "voice latency :: it is about 600ms\nunicorns :: they are real"

            return Answer()

    found = distil.summarise_memories(Inventing(), [{"subject": "voice latency", "count": 4}])

    assert found == [("voice latency", "it is about 600ms")]


def test_no_model_still_promotes_what_repeats() -> None:
    """The count-based pass is what reflection always did, and it must keep
    working when there is nothing to ask."""
    from marvi_gateway import distil

    assert distil.summarise_memories(None, [{"subject": "voice latency", "count": 4}]) == []


def test_a_short_page_is_not_worth_summarising() -> None:
    """It is already the answer, and a round trip to say so is a round trip
    wasted."""
    from marvi_gateway import distil

    class Loud:
        def call_with_fallback(self, *_a, **_k):
            raise AssertionError("should not have been called")

    assert distil.extract_answer(Loud(), "short page", "what does it say") == ""


def test_a_page_with_no_question_is_passed_through_whole() -> None:
    from marvi_gateway import distil

    assert distil.extract_answer(None, "x" * 5000, "") == ""
