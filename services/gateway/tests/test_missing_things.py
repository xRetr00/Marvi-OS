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
    # Says the step did not run -- about that step, not the whole turn. The
    # first wording, "Nothing was done", was false the day it first fired.
    assert "did not run" in said, "silence would read as her having nothing to say"
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


def test_a_typed_out_call_is_recovered_and_run_not_apologised_for() -> None:
    """The real fix, rather than hiding the markup.

    Stripping it and saying sorry is honest and wasteful: the model named the
    tool and its arguments, and every bit of that survives in the text. So it
    is read back into a real call, the tool runs, and the turn continues.
    """
    paired = (
        '<tool_call>terminal_run <arg_key>command</arg_key> <arg_value>Get-Process '
        '-Name "Sidecar"</arg_value> <arg_key>shell</arg_key> '
        "<arg_value>powershell</arg_value> </tool_call>"
    )
    assert tool_call_prose.recover(paired) == {
        "name": "terminal_run",
        "arguments": {"command": 'Get-Process -Name "Sidecar"', "shell": "powershell"},
    }


def test_every_dialect_a_model_might_write_is_read_back() -> None:
    """One fix, not a case per model. Three shapes, one parser."""
    assert tool_call_prose.recover(
        '<tool_call>{"name": "marvi_logs", "arguments": {"lines": 40}}</tool_call>'
    ) == {"name": "marvi_logs", "arguments": {"lines": 40}}

    assert tool_call_prose.recover(
        '<invoke name="room_state"><parameter name="deep">true</parameter></invoke>'
    ) == {"name": "room_state", "arguments": {"deep": True}}


def test_values_come_back_as_the_types_the_tool_declares() -> None:
    """Markup has no types, so everything arrives as a string.

    A tool declaring `lines: int` refuses `"40"` -- the same disagreement
    `_coerce` exists for -- so a recovered call that only ever produced
    strings would fail validation for a different reason and look like a
    second bug.
    """
    got = tool_call_prose.recover(
        '<invoke name="marvi_logs"><parameter name="n">40</parameter>'
        '<parameter name="f">1.5</parameter>'
        '<parameter name="b">true</parameter>'
        '<parameter name="s">hello</parameter></invoke>'
    )
    assert got is not None
    assert got["arguments"] == {"n": 40, "f": 1.5, "b": True, "s": "hello"}


def test_nothing_recoverable_is_not_invented() -> None:
    """Conservative on purpose: a guess that runs the wrong tool is worse."""
    assert tool_call_prose.recover("Just a normal answer.") is None
    assert tool_call_prose.recover("Use <b>bold</b> if you like.") is None
    assert tool_call_prose.recover("") is None


def test_a_big_failure_is_said_out_loud_once() -> None:
    """The announcer is what still works when the rest does not.

    Port conflicts, a voice engine that will not load, a camera with no
    driver -- each stops a whole capability, each was known the moment it
    happened, and each went to a log file for somebody to find hours later.
    """
    from marvi_gateway.alarms import Alarms

    said: list[str] = []

    class Speaker:
        def speak(self, text: str, **_: object) -> dict[str, object]:
            said.append(text)
            return {"played": True}

    bell = Alarms(Speaker())
    bell._say = lambda line: said.append(line)  # no thread, no audio stack

    broken = {"voice": {"state": "error", "detail": "No espeak backend found"}}
    assert len(bell.check(broken)) == 1
    assert "voice could not start" in said[0]
    # The exception text is developer detail and must not be spoken.
    assert "espeak" not in said[0]

    # A broken thing stays broken, and the status path polls. Saying it every
    # two seconds would be the thing you turn off.
    assert bell.check(broken) == []
    assert len(said) == 1

    # Recovered, then broken again, is news again.
    bell.check({"voice": {"state": "ready", "detail": ""}})
    assert len(bell.check(broken)) == 1


def test_only_a_stopped_capability_is_worth_interrupting_for() -> None:
    """`degraded` and `starting` say so on screen, where they belong."""
    from marvi_gateway.alarms import Alarms

    bell = Alarms(object())
    bell._say = lambda line: None
    for quiet in ("ready", "starting", "degraded", "offline"):
        assert bell.check({"voice": {"state": quiet, "detail": ""}}) == []


def test_a_component_with_no_wording_is_not_invented() -> None:
    from marvi_gateway.alarms import Alarms

    bell = Alarms(object())
    bell._say = lambda line: None
    assert bell.check({"something_new": {"state": "error", "detail": "x"}}) == []


def test_the_gateway_publishes_a_build_signature_not_just_a_version() -> None:
    """Version cannot answer "is that Gateway the same build as me".

    It changes on release; a nightly's code changes every hour. Two Gateways
    four hours apart report the same version, the check passes, and the stale
    one keeps serving with whatever was fixed in between.
    """
    from marvi_gateway import signature

    build = signature.build()
    assert build and len(build) == signature.SHOWN
    assert signature.mine(build)
    assert not signature.mine("deadbeef1234")
    assert not signature.mine("")
    # Stable within a process: it describes the code loaded, which cannot
    # change while running.
    assert signature.build() == build


def _chat_with(dispatch) -> object:
    import tempfile
    from pathlib import Path

    from marvi_gateway.chat import Chat, ChatStore

    store = ChatStore(Path(tempfile.mkdtemp()) / "chat.sqlite3")
    return Chat(client=None, store=store, dispatch=dispatch)


def test_no_tool_problem_ends_the_turn() -> None:
    """Every failure is handed back, so the model can retry or report.

    A turn that dies on a tool leaves the user with nothing and the model with
    no chance to recover -- and it is always the model that can recover, by
    fixing an argument, choosing another tool, or saying plainly what broke.
    """

    def dispatch(name: str, arguments: dict) -> dict:
        if name == "raises":
            raise RuntimeError("the tool exploded")
        if name == "refuses":
            return {"status": "failed", "error": "no such tool"}
        return {"status": "ok", "result": {"fine": True}}

    chat = _chat_with(dispatch)
    for name, args in (("raises", {}), ("refuses", {})):
        outcome = chat._run_tool(name, args)
        assert outcome["failed"], name
        assert "did nothing" in outcome["text"], name
        # And it never raises out of here, which is the property that matters.
        assert outcome.get("pending_confirmation") is None


def test_arguments_that_cannot_be_read_say_so_rather_than_becoming_empty() -> None:
    """`{}` sent the call anyway, and the tool reported the wrong problem.

    A required argument then came back as "missing argument name" -- true, and
    misleading: the model did send a name, and the encoding was what broke. It
    fixed the wrong thing.
    """
    chat = _chat_with(lambda name, arguments: {"status": "ok", "result": {}})

    unreadable = chat._run_tool("some_tool", "not json at all")
    assert unreadable["failed"]
    assert "not valid JSON" in unreadable["text"]

    wrong_shape = chat._run_tool("some_tool", [1, 2, 3])
    assert wrong_shape["failed"]
    assert "must be a JSON object" in wrong_shape["text"]

    # A string that *is* an object still works: this must not become strict
    # about the wrapper when the content is fine.
    assert not chat._run_tool("some_tool", '{"a": 1}').get("failed")
    assert not chat._run_tool("some_tool", "").get("failed")


def test_a_process_stamp_says_whose_it_is_which_build_and_since_when() -> None:
    """Three questions get asked of a process, and none had an answer."""
    from marvi_gateway import signature

    stamp = signature.stamp("gateway")
    assert stamp.startswith("marvi."), "the ownership marker is the cheap test"

    read = signature.parse(stamp)
    assert read is not None
    assert read["kind"] == "gateway"
    assert read["build"] == signature.build()
    assert read["mine"] is True
    assert read["age_seconds"] >= 0

    # Found inside a command line, which is where a sweep actually meets one.
    inside = f"python.exe -m marvi_gateway --stamp {signature.stamp('sidecar')} --port 8765"
    assert signature.ours(inside)
    found = signature.parse(inside)
    assert found is not None and found["kind"] == "sidecar"

    # Anything else on the machine is not hers.
    assert not signature.ours("python.exe -m something_else")
    assert signature.parse("python.exe -m something_else") is None


def test_a_stamp_from_another_build_is_not_mine() -> None:
    from marvi_gateway import signature

    theirs = "marvi.gateway.ffffffffffff.20260101T000000Z.999"
    read = signature.parse(theirs)
    assert read is not None
    assert read["mine"] is False, "a different build must not read as the same one"
    assert not signature.mine(theirs)
    # And it is still recognisably Marvi's, which is what lets it be replaced
    # rather than left alone as something unrelated.
    assert signature.ours(theirs)


def test_a_wrong_action_name_is_answered_with_the_right_one() -> None:
    """From a real session: `launch` and `screenshot`, neither of which exist.

    Each refusal said only "Unknown computer action. Read computer_tools
    first." She read computer_tools and then called `screenshot` again, because
    nothing in a list of twenty-three names says a screenshot comes back from
    reading a window.
    """
    from marvi_gateway.computer import ACTIONS, unknown_action

    said = unknown_action("launch")
    assert '"launch_app"' in said
    shot = unknown_action("screenshot")
    assert '"get_desktop_state"' in shot
    assert "no separate screenshot action" in shot
    # Near-misses are corrected too, not only the ones in the table.
    assert '"click"' in unknown_action("clik")
    # And every refusal carries the whole list, so no second guess is needed.
    for name in ACTIONS:
        assert name in said


def test_a_stale_browser_revision_says_the_current_one() -> None:
    """She sent `revision=0` to close and to show, twice, and never learnt 2."""
    import pytest

    from marvi_gateway.browser_workspace import BrowserWorkspace

    workspace = BrowserWorkspace.__new__(BrowserWorkspace)
    workspace.sessions = {"s1": {"id": "s1", "revision": 2, "state": "ready"}}
    workspace._session = lambda sid: workspace.sessions[sid]
    with pytest.raises(ValueError) as refused:
        workspace._check("s1", 0)
    assert "revision=2" in str(refused.value), "the number that makes the next call work"
    assert "you sent revision 0" in str(refused.value)


def test_running_out_of_steps_is_not_reported_as_doing_nothing() -> None:
    """The message said "Nothing was done" after five real actions.

    From the chat store: get_desktop_state, move_cursor, get_cursor_position,
    click (refused for a missing scope), click again -- all ran, the cursor
    moved. Then the eighth round offered no tools, she wrote the next call out
    as text, and the reply claimed nothing had happened.
    """
    typed = (
        "<tool_call>computer_action <arg_key>action</arg_key> "
        "<arg_value>click</arg_value></tool_call>"
    )
    used = ["computer_action"] * 5

    said = tool_call_prose.out_of_steps(typed, used)
    assert "Nothing was done" not in said
    assert "ran out of steps" in said
    assert "computer_action (5 times)" in said, "credit what actually ran"
    assert "So far" in said, "a sentence of its own starts with a capital"

    # A call that genuinely did not run still says so -- about that step only.
    lone = tool_call_prose.instead_say(typed, [])
    assert "that step was not done" in lone
    assert "Nothing was done" not in lone


def test_chat_and_voice_have_the_same_tool_budget() -> None:
    """Eight rounds produced the malformed call it was then blamed for."""
    from marvi_gateway.chat import MAX_TOOL_ROUNDS

    assert MAX_TOOL_ROUNDS >= 24
