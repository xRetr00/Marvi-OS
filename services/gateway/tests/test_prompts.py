"""The prompt registry, and the inventory of what has not moved into it yet.

Nineteen prompt constants lived in seventeen modules. The cost was not the
duplication -- it was that nobody could find them. `deliberate.SYSTEM_PROMPT`
said "Silence is the normal, correct answer" while `config/personas/default.md`
said "Judgement, not silence by default", and the contradiction survived
because there was no list of places a prompt could be.

So there is a list. It only shrinks.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from marvi_gateway import prompts

REPO = Path(__file__).resolve().parents[3]

#: Prompt-sized string constants still living in code, with their sizes.
#:
#: Every one of these is a prompt that cannot be found by looking in
#: `prompts/`. Moving one means deleting its line here; adding a new one means
#: this test fails and asks you to write a file instead. That is the whole
#: mechanism -- the list is allowed to get shorter and never longer.
#:
#: `SCHEMA` constants are database DDL rather than instructions and are not
#: counted; see `_is_prompt`.
STILL_IN_CODE = {
    ("remembering.py", "SYSTEM_PROMPT"),
    ("distil.py", "TITLE_SYSTEM"),
    ("gatekeeping.py", "SYSTEM_PROMPT"),
    ("memory_import.py", "SYSTEM_PROMPT"),
    ("dreaming.py", "SYSTEM_PROMPT"),
    ("learning.py", "SYSTEM_PROMPT"),
    ("gatekeeping.py", "ONE_SYSTEM_PROMPT"),
    ("rephrasing.py", "SYSTEM_PROMPT"),
    ("memory_import.py", "PACK_PROMPT"),
    ("standing.py", "SYSTEM_PROMPT"),
    ("presence.py", "SYSTEM_PROMPT"),
    ("distil.py", "MEMORY_SYSTEM"),
    ("continuity.py", "SYSTEM_PROMPT"),
    ("screen.py", "SYSTEM_PROMPT"),
    ("identity.py", "PLAN_TERMS_WARNING"),
    ("distil.py", "EXTRACT_SYSTEM"),
    # The Agent service, which has the same problem for the same reason.
    ("session.py", "DEFAULT_REPLY_RULE"),
    ("session.py", "TOOL_SEARCH_NOTE"),
}

#: Below this, a string constant is a message or a label rather than a prompt.
PROMPT_SIZED = 200


def _is_prompt(name: str, value: str) -> bool:
    return name.isupper() and "SCHEMA" not in name and len(value) >= PROMPT_SIZED


def _constants_in_code() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in (REPO / "services").rglob("*.py"):
        if ".venv" in path.parts or "tests" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            try:
                value = ast.literal_eval(node.value)
            except Exception:
                continue
            if not isinstance(value, str):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and _is_prompt(target.id, value):
                    found.add((path.name, target.id))
    return found


def test_no_new_prompt_is_hidden_in_a_module() -> None:
    """A new prompt goes in `prompts/`, not in a constant nobody can find."""
    now = _constants_in_code()
    if new := now - STILL_IN_CODE:
        listed = ", ".join(f"{where}:{what}" for where, what in sorted(new))
        pytest.fail(
            f"new prompt constant(s) in code: {listed}. Write a file in prompts/ "
            "and load it with prompts.text(), or add it to STILL_IN_CODE with a "
            "reason if it genuinely is not a prompt."
        )


def test_the_debt_list_does_not_go_stale() -> None:
    """A migrated prompt has to leave the list, or the list stops meaning anything."""
    if gone := STILL_IN_CODE - _constants_in_code():
        listed = ", ".join(f"{where}:{what}" for where, what in sorted(gone))
        pytest.fail(f"no longer in code, delete from STILL_IN_CODE: {listed}")


def test_every_prompt_file_is_loadable_and_described() -> None:
    every = prompts.catalogue()
    assert every, "no prompt files found"
    for one in every:
        assert one.description, f"{one.key} has no description"
        assert one.body.strip(), f"{one.key} is empty"


def test_a_missing_variable_is_an_error_not_a_literal_dollar_brace() -> None:
    """`${STANCE}` reaching a model reads as an instruction it cannot follow."""
    with pytest.raises(prompts.PromptError, match="STANCE"):
        prompts.text("mind-deliberation")
    with pytest.raises(prompts.PromptError, match="does not use"):
        prompts.text("mind-deliberation", STANCE="x", NONSENSE="y")


def test_a_dollar_in_prose_survives_substitution() -> None:
    """The chat prompt tells the model to write maths as `$...$ or $$...$$`.

    `string.Template` reads `$$` as an escaped dollar and collapsed it, so the
    instruction shipped having lost the half it existed to give.
    """
    filled = prompts.text("chat", LANGUAGE="Reply in English.")
    assert "$...$ or $$...$$" in filled
    assert "Reply in English." in filled


def test_the_two_surfaces_ask_for_different_things() -> None:
    """Voice and chat differ by medium, and the prompts have to say so."""
    voice = prompts.text("voice-assistant", LANGUAGE="Reply in English.")
    typed = prompts.text("chat", LANGUAGE="Reply in English.")
    assert "No Markdown" in voice
    assert "Markdown when structure helps" in typed


def test_an_agent_prompt_declares_when_to_use_it() -> None:
    """Routing information lives with the prompt, not in the dispatcher.

    Claude Code keeps `whenToUse` in the prompt file so the description a
    router reads and the instructions the agent gets cannot drift apart. Marvi
    has no sub-agent system yet -- `coding-agent` is handed to an outside CLI
    -- so this is written ahead of the runtime that will read it.
    """
    coding = prompts.get("coding-agent")
    assert coding.is_agent
    assert "coding" in coding.when_to_use.lower()
    # It must not be able to talk to the room or hang up on anybody.
    assert "speak" in coding.denied_tools
    assert "end_conversation" in coding.denied_tools
    assert prompts.agents() == [coding]


def test_the_coding_brief_says_what_a_delegated_agent_kept_getting_wrong() -> None:
    """Each of these is a habit an unbriefed run actually produced."""
    brief = prompts.text("coding-agent", MODE="investigate", ROOT="D:/Marvi-OS")
    assert "D:/Marvi-OS" in brief and "Mode: investigate" in brief
    # Reports came back as bullet lists of file paths, which cannot be spoken.
    assert "read your final report to someone out loud" in brief.replace(chr(10), " ")
    # And the pipe-exit-status mistake, which shipped a segfaulting suite green.
    assert "not the exit status of something you piped it into" in brief.replace(chr(10), " ")
