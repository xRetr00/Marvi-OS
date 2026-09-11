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
#: Large string constants that are not prompts.
#:
#: The scan matches on size and an upper-case name, which is the right net for
#: a prompt and catches the odd thing that merely looks like one. Each entry
#: needs a reason, so the list cannot quietly become a place to hide prompts.
STILL_IN_CODE: set[tuple[str, str]] = {
    # The MARVI OS banner: box-drawing characters, printed to a terminal.
    ("terminal_ui.py", "MARVI_ART"),
    # The /help reply the Telegram bot sends a person. Never shown to a model.
    ("telegram.py", "HELP"),
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
    """Voice and chat differ by medium, and the prompts have to say so.

    Not by looking for "No Markdown" in the voice prompt -- that rule belongs
    to the persona, because it is the one thing `chat` reverses. What the voice
    prompt owns is everything about the input being *heard*: a transcript that
    may have got a name wrong, and `clarify` rather than saying the word.
    """
    voice = prompts.text(
        "voice-assistant",
        SITUATION="Right now it is Tuesday.",
        LANGUAGE="Reply in English.",
        ARCHITECTURE="",
    )
    typed = prompts.text("chat", LANGUAGE="Reply in English.")
    assert "reading a transcript of speech, not typing" in voice
    assert "the microphone is the likeliest reason" in voice
    assert "Markdown when structure helps" in typed
    assert "transcript" not in typed


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
    # The brief for outside coders declares no tools of its own: they bring
    # theirs. It is not something the sub-agent runner can start.
    assert not coding.runnable


def test_the_built_in_sub_agents_are_runnable_agents() -> None:
    """Harvi, Jarvi, Talos and the generic worker ship as prompt files."""
    runnable = {one.key: one for one in prompts.agents() if one.runnable}
    assert set(runnable) == {"harvi", "jarvi", "talos", "worker"}
    # Harvi has every tool; the worker too, under a generated name.
    assert runnable["harvi"].tools == ("*",)
    assert runnable["worker"].tools == ("*",)
    assert len(runnable["worker"].names) >= 4
    assert not runnable["harvi"].names
    assert "computer_action" in runnable["jarvi"].tools
    assert "browser_action" in runnable["talos"].tools
    assert runnable["harvi"].max_rounds > runnable["jarvi"].max_rounds
    # Its harness names the coding tools it is expected to reach for.
    for tool in ("grep", "glob", "file_read", "todo_write", "process_output"):
        assert f"`{tool}`" in runnable["harvi"].body


def test_agent_frontmatter_declares_tools_model_and_rounds(tmp_path) -> None:
    folder = tmp_path / "prompts"
    folder.mkdir()
    (folder / "scout.md").write_text(
        "<!--\n"
        'name: "Agent: Scout"\n'
        'description: "Looks around."\n'
        'when-to-use: "When looking around."\n'
        "tools:\n"
        '  - "web_search"\n'
        '  - "web_fetch"\n'
        'model: "aux"\n'
        "max-rounds: 40\n"
        "-->\n"
        "You look around.\n",
        encoding="utf-8",
    )
    prompts.forget()
    try:
        scout = prompts.get("scout", tmp_path)
    finally:
        prompts.forget()
    assert scout.tools == ("web_search", "web_fetch")
    assert scout.model == "aux"
    assert scout.max_rounds == 40
    assert scout.runnable


def test_the_coding_brief_says_what_a_delegated_agent_kept_getting_wrong() -> None:
    """Each of these is a habit an unbriefed run actually produced."""
    brief = prompts.text("coding-agent", MODE="investigate", ROOT="D:/Marvi-OS")
    assert "D:/Marvi-OS" in brief and "Mode: investigate" in brief
    # Reports came back as bullet lists of file paths, which cannot be spoken.
    assert "read your final report to someone out loud" in brief.replace(chr(10), " ")
    # And the pipe-exit-status mistake, which shipped a segfaulting suite green.
    assert "not the exit status of something you piped it into" in brief.replace(chr(10), " ")


#: The floor a tool description has to clear.
#:
#: Marvi's median was 38 characters. `send_email` -- outward-facing, no undo --
#: was "Send an email", so the model had to infer from three words that it
#: should confirm first, that there is no unsend, and that retrying a partial
#: failure can deliver two. Nothing made that visible, which is why it stayed
#: that way across every tool.
SHORTEST_USEFUL_DESCRIPTION = 120


def test_every_tool_description_lives_in_a_file() -> None:
    """A description is prompt text: it is the whole basis for calling a tool."""
    from marvi_gateway import tools as tooling

    described = prompts.tools()
    assert len(described) >= 60, "the tool descriptions did not load"

    registry = tooling.ToolRegistry()
    registry.register(
        tooling.ToolSpec("send_email", "Send an email", {}, True, lambda: None)
    )
    # The file wins over the call site, which is what makes the file the source.
    assert "there is no unsend" in registry.get("send_email").description


def test_a_tool_with_no_file_keeps_what_it_was_given() -> None:
    """MCP servers register at runtime and cannot have shipped a file."""
    from marvi_gateway import tools as tooling

    registry = tooling.ToolRegistry()
    registry.register(
        tooling.ToolSpec("mcp__somewhere__thing", "Whatever it does", {}, False, lambda: None)
    )
    assert registry.get("mcp__somewhere__thing").description == "Whatever it does"


def test_no_tool_is_described_in_three_words() -> None:
    short = {
        name: len(said)
        for name, said in prompts.tools().items()
        if len(said) < SHORTEST_USEFUL_DESCRIPTION
    }
    assert not short, (
        f"too thin to choose from: {short}. A description says what the tool does, "
        "when to reach for it, when not to and what to use instead, and the mistake "
        "that has actually been made with it."
    )


def test_the_dangerous_tools_say_they_cannot_be_undone() -> None:
    """Each of these reaches outside the machine or destroys something."""
    described = prompts.tools()
    for name, must_say in (
        ("send_email", "no unsend"),
        ("memory_forget", "no undo"),
        ("file_delete", "cannot be undone"),
        ("calendar_remove", "cannot be undone"),
    ):
        assert must_say in described[name].lower().replace("\n", " "), name


def test_every_area_word_finds_its_tools() -> None:
    """An index that names a query returning nothing is worse than no index.

    The deferred-tools block tells the model, per area, the exact word to
    search with -- copied from how Claude Code names the `ToolSearch` query for
    a toolkit rather than saying "search if you need something". That is only
    worth anything if the words work, so they are checked against the real
    search rather than assumed.
    """
    from marvi_gateway import toolsearch

    described = prompts.tools()
    catalogue = [
        {"name": name, "description": said, "arguments": [], "optional": [], "input_schema": {}}
        for name, said in described.items()
    ]
    core = toolsearch.core_tools()
    deferred = [name for name in described if name not in core]

    for label, word, mine in toolsearch.by_area(deferred):
        found = {row["name"] for row in toolsearch.search(catalogue, word, 12)}
        missed = set(mine) - found
        assert not missed, f"searching {word!r} for {label!r} does not find {sorted(missed)}"


def test_no_tool_is_left_out_of_the_index() -> None:
    """A tool nobody lists is a tool the model has no reason to suspect."""
    from marvi_gateway import toolsearch

    deferred = [n for n in prompts.tools() if n not in toolsearch.core_tools()]
    listed = [name for _, _, names in toolsearch.by_area(deferred) for name in names]
    assert sorted(listed) == sorted(deferred)
    assert len(listed) == len(set(listed)), "a tool is listed under two areas"


def test_the_deferred_block_forbids_denying_a_capability() -> None:
    """The rule that Marvi's own measured failure needed.

    Deferral was tried, produced twenty-three refusals of things she can do
    across 123 turns, and was switched off. Claude Code's answer is a standing
    rule -- do not assert a missing capability from general knowledge -- plus
    always-visible names. Both are in this block.
    """
    block = prompts.text("deferred-tools", AREAS="- **email** -- search `email`: send_email")
    assert "Never say you cannot do something" in block
    assert "search that found nothing" in block
    assert "send_email" in block
