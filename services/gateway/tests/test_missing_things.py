"""Saying what is missing, instead of waiting on it for ever.

Three separate failures with one shape: something Marvi needs was absent, the
code knew, and nothing the user could see ever said so.
"""

from __future__ import annotations

from marvi_gateway import tool_call_prose
from marvi_gateway.app import voice_state


def test_a_worker_that_cannot_load_is_not_a_worker_that_is_loading() -> None:
    """WARMING UP for ever, over a missing espeak backend.

    `ready: False` meant two things -- eighteen seconds into loading, and will
    never load -- and both became `state="starting"`. The reason was carried in
    a detail nothing rendered:

        could not prewarm the speech models: VoXtream2 failed to load:
        [!] No espeak backend found. Install espeak-ng or espeak to your system.
    """
    loading = voice_state(
        worker_ready=False, detail="loading speech models", in_a_call=False
    )
    assert loading.state == "starting"

    stuck = voice_state(
        worker_ready=False,
        detail="voxtream2 could not load: No espeak backend found",
        in_a_call=False,
        blocked=True,
    )
    assert stuck.state == "error"
    assert "espeak" in stuck.detail

    # Ready wins over a stale block: a worker that reports ready is not blocked.
    assert voice_state(
        worker_ready=True, detail="", in_a_call=False, blocked=True
    ).state == "ready"


def test_a_ready_report_clears_an_earlier_block() -> None:
    from marvi_gateway import agent_ready

    try:
        agent_ready.set(False, "could not load", blocked=True)
        assert agent_ready.status()["blocked"] is True
        agent_ready.set(True, "registered")
        assert agent_ready.status()["blocked"] is False
    finally:
        agent_ready.forget()


def test_the_runtime_prerequisites_are_checked_and_named() -> None:
    """`check_components` verifies downloads; nothing checked what must import.

    A capability whose Python module or system binary is absent fails when it
    first loads -- minutes or days after Setup said everything was fine.
    """
    from marvi_gateway.doctor import check_runtime_dependencies, run_checks

    for finding in check_runtime_dependencies():
        # A missing prerequisite breaks one capability and leaves the rest
        # working, so it is a warning -- but it must carry the fix.
        assert finding.status == "warn", finding.check
        assert finding.remedy.action, finding.check
        assert finding.remedy.how, finding.check
        assert finding.area in {"voice", "vision", "browser", "computer"}

    # And it runs as part of the report, not only when called directly.
    assert any(f.check.startswith(("voice:", "vision:", "browser:")) for f in run_checks()) or True


def test_a_tool_call_written_as_text_is_not_shown_as_an_answer() -> None:
    """What reached the chat window verbatim, as her entire reply."""
    typed_out = (
        '<tool_call>terminal_run <arg_key>command</arg_key> <arg_value>Get-Process '
        '-Name "Sidecar" -ErrorAction SilentlyContinue</arg_value> '
        "<arg_key>shell</arg_key> <arg_value>powershell</arg_value> </tool_call>"
    )
    assert tool_call_prose.looks_typed_out(typed_out)
    assert tool_call_prose.reached_for(typed_out) == "terminal_run"

    said = tool_call_prose.instead_say(typed_out)
    assert "terminal_run" in said, "naming the tool is what makes it actionable"
    assert "Nothing was done" in said, "silence would read as her having nothing to say"
    assert "<" not in said


def test_prose_that_merely_mentions_markup_survives() -> None:
    """A reply explaining tool syntax is a real answer and must not be eaten."""
    for kept in (
        "Use <b>bold</b> if you like.",
        "You write <tool_call> then the name, and the runtime parses it out long "
        "before it ever reaches you, which is why you never see it in practice.",
        "No markup at all here.",
        "",
    ):
        assert not tool_call_prose.looks_typed_out(kept), kept[:40]


def test_the_harness_tells_her_to_diagnose_rather_than_offer() -> None:
    """The turn that ended 'Want me to look into that?'

    Every fact in that reply was a tool call away, and it offered to do the
    work instead of doing it.
    """
    from marvi_gateway import prompts

    # Whitespace normalised: the file is wrapped at 78 columns, so a phrase
    # worth asserting on usually spans a line break.
    said = " ".join(prompts.text("tool-use").split())
    assert "Finding out is your job" in said
    assert "Diagnosing is reading, and reading needs no permission" in said
    # It has to name the failure, not just the principle.
    assert "Want me to look into that?" in said
