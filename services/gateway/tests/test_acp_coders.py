"""Outside coders over the Agent Client Protocol.

These run the real SDK against a real subprocess speaking ACP over stdio
(`fixtures/fake_acp_agent.py`), so the protocol boundary is exercised, not
mocked: initialize, a session, the mode Marvi chooses, streamed updates, a
permission request, and cancel.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from marvi_gateway import acp_coders, subagents
from marvi_gateway.tools import ToolRegistry

FAKE = Path(__file__).parent / "fixtures" / "fake_acp_agent.py"


class Tools:
    def __init__(self, **outcomes: dict[str, Any]) -> None:
        self.outcomes = outcomes
        self.seen: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.seen.append((name, arguments))
        return self.outcomes.get(name, {"status": "executed", "result": {"approved": True}})


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVI_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        acp_coders,
        "CODERS",
        {"fake": acp_coders.Coder("fake", "Fake Coder", "A test coder.", lambda: [sys.executable, str(FAKE)])},
    )
    return tmp_path


def runner(tools: Tools | None = None, **kwargs: Any) -> subagents.Runner:
    return subagents.Runner(object(), lambda: [], tools or Tools(), **kwargs)


def finished(run: subagents.Runner, answer: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
    assert answer["ok"], answer
    run.wait(answer["id"], timeout)
    return run.job(answer["id"])


def test_an_outside_coder_runs_over_acp_and_reports(fake) -> None:
    run = runner()
    job = finished(run, run.start("fake", "look at calc.py"))

    assert job["state"] == "completed", job
    assert job["summary"] == "Done: no permission asked, mode=plan."
    kinds = [event["kind"] for event in job["events"]]
    assert kinds[:3] == ["said", "tool", "said"] or "tool" in kinds
    read = next(event for event in job["events"] if event["kind"] == "tool")
    assert read["text"] == "read: Read calc.py" and read["outcome"] == "ok"
    assert job["todos"] == [{"content": "Look at it", "status": "completed"}]
    assert job["name"] == "Fake Coder"


def test_investigate_asks_for_the_read_only_mode_and_fix_for_edits(fake) -> None:
    run = runner()
    investigate = finished(run, run.start("fake", "look"))
    fix = finished(run, run.start("fake", "change it", mode="fix"))

    assert "mode=plan" in investigate["summary"]
    assert "mode=acceptEdits" in fix["summary"]


def test_a_fix_job_edits_without_asking_again(fake) -> None:
    tools = Tools()
    run = runner(tools)

    job = finished(run, run.start("fake", "ask:edit", mode="fix"))

    assert "allowed" in job["summary"]
    assert tools.seen == []


def test_investigate_refuses_an_edit_outright(fake) -> None:
    tools = Tools()
    run = runner(tools)

    job = finished(run, run.start("fake", "ask:edit"))

    assert "rejected" in job["summary"]
    assert tools.seen == [], "a read-only job does not ask the owner to approve an edit"


def test_anything_else_goes_to_the_owner_through_marvis_confirmation(fake) -> None:
    """A network fetch is not covered by the fix grant: it becomes an ordinary
    Marvi confirmation, and the job waits for it like any sub-agent."""
    tools = Tools(coder_permission={"status": "confirmation_required", "token": "t9"})
    live = {"t9"}
    run = runner(tools, pending=lambda token: token in live)
    started = run.start("fake", "ask:fetch", mode="fix")

    deadline = time.monotonic() + 20
    while run.status(started["id"])["state"] != "awaiting_approval":
        assert time.monotonic() < deadline, run.job(started["id"])
        time.sleep(0.02)
    parked = run.status(started["id"])
    assert "fetch" in parked["action"]

    live.clear()
    run.settling("t9")
    run.settled("t9", {"status": "denied"})

    job = finished(run, started)
    assert "rejected" in job["summary"]
    assert tools.seen[0][0] == "coder_permission"
    assert tools.seen[0][1]["coder"] == "fake"


def test_yolo_allows_what_the_owner_would_be_asked(fake) -> None:
    tools = Tools(coder_permission={"status": "executed", "result": {"approved": True}})
    run = runner(tools)

    job = finished(run, run.start("fake", "ask:fetch", mode="fix"))

    assert "allowed" in job["summary"]


def test_stop_cancels_the_session(fake) -> None:
    run = runner()
    started = run.start("fake", "slow")
    deadline = time.monotonic() + 20
    while not any(e["kind"] == "tool" for e in (run.job(started["id"]) or {}).get("events", [])):
        assert time.monotonic() < deadline
        time.sleep(0.05)

    run.stop(started["id"])
    job = finished(run, started)

    assert job["state"] == "interrupted"


def test_a_refusal_is_a_failure(fake) -> None:
    run = runner()
    job = finished(run, run.start("fake", "refuse"))

    assert job["state"] == "failed"
    assert "will not do that" in job["summary"]


def test_a_coder_that_cannot_start_fails_plainly(fake, monkeypatch) -> None:
    monkeypatch.setattr(
        acp_coders,
        "CODERS",
        {"fake": acp_coders.Coder("fake", "Fake", "x", lambda: ["no-such-binary-marvi"])},
    )
    run = runner()
    job = finished(run, run.start("fake", "look"))

    assert job["state"] == "failed"
    assert "could not start" in job["summary"]


def test_outside_coders_join_the_roster_only_when_installed(fake, monkeypatch) -> None:
    run = runner()
    assert "fake" in [agent["key"] for agent in run.overview()["agents"]]

    monkeypatch.setattr(
        acp_coders, "CODERS", {"fake": acp_coders.Coder("fake", "Fake", "x", lambda: None)}
    )
    assert "fake" not in [agent["key"] for agent in run.overview()["agents"]]
    assert not run.start("fake", "look")["ok"]


def test_delegate_to_coder_now_runs_over_acp(fake) -> None:
    registry = ToolRegistry()
    run = runner()
    subagents.register_subagent_tools(registry, run)

    answer = registry.get("delegate_to_coder").handler(task="look", coder="fake")
    assert answer["ok"] and answer["agent"] == "fake"
    run.wait(answer["id"], 30)
    assert registry.get("delegate_to_coder").sensitive


def test_the_permission_tool_is_callable_but_never_offered() -> None:
    """It is a confirmation carrier, not a capability: no model sees it."""
    registry = ToolRegistry()
    subagents.register_subagent_tools(registry, runner())

    assert registry.get("coder_permission").sensitive
    assert "coder_permission" not in {spec.name for spec in registry}


def test_a_permission_request_waits_while_the_job_is_threaded(fake) -> None:
    """The job thread owns an event loop; the approval wait must not block the
    loop that is reading the agent's stream."""
    gate = threading.Event()

    def slow_tools(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        gate.wait(2)
        return {"status": "executed", "result": {"approved": True}}

    run = runner(slow_tools)
    job = finished(run, run.start("fake", "ask:fetch", mode="fix"))
    assert "allowed" in job["summary"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows program resolution")
def test_an_adapter_is_started_through_something_windows_can_run(monkeypatch) -> None:
    """The first real run died with WinError 193: `which("npx")` found npm's
    extensionless sh script. What is resolved must be a runnable file."""
    command = acp_coders._adapter(acp_coders.CODEX_ACP, "codex")()
    if command is None:
        pytest.skip("codex is not installed here")
    assert command[0].lower().endswith((".exe", ".cmd", ".bat"))
