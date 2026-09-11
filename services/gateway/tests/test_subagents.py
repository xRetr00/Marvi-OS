"""Sub-agents: Harvi, Jarvi, Talos and the generic worker.

What matters is the contract, not that a thread runs: only the final report
comes back, a sub-agent cannot reach a tool Marvi keeps for herself, a job that
needs the owner's say-so waits for it, and nothing can hold a job forever.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from marvi_gateway import subagents
from marvi_gateway.providers import Completion, Usage
from marvi_gateway.tools import ToolRegistry

AVAILABLE = [
    "file_read", "file_edit", "file_write", "file_delete", "grep", "glob",
    "terminal_run", "web_search", "computer_status", "computer_action",
    "browser_action", "memory_remember", "telegram_send", "delegate", "clarify",
]


def reply(text: str = "", calls: list[dict[str, Any]] | None = None) -> Completion:
    return Completion(
        text=text, usage=Usage(input=10, output=5), provider="test", model="m",
        tool_calls=calls or [],
    )


def call(name: str, **arguments: Any) -> dict[str, Any]:
    return {"id": f"c-{name}-{time.monotonic_ns()}", "name": name, "arguments": arguments}


class Script:
    """A provider that answers from a list. A callable entry sees the messages."""

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []

    def call_with_fallback(self, messages, **kwargs):
        self.calls.append(([dict(m) for m in messages], kwargs))
        answer = self.replies.pop(0) if self.replies else reply("done")
        return answer(messages) if callable(answer) else answer

    def offered(self, index: int = 0) -> set[str]:
        return {tool["name"] for tool in self.calls[index][1].get("tools") or []}


class Tools:
    """The Gateway's dispatch, recorded. Outcomes by tool name."""

    def __init__(self, **outcomes: dict[str, Any]) -> None:
        self.outcomes = outcomes
        self.seen: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.seen.append((name, arguments))
        return self.outcomes.get(name, {"status": "executed", "result": {"ok": name}})

    def names(self) -> list[str]:
        return [name for name, _ in self.seen]


def schemas() -> list[dict[str, Any]]:
    return [{"name": name, "description": name, "parameters": {"type": "object"}} for name in AVAILABLE]


@pytest.fixture
def root(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("MARVI_WORKSPACE_ROOT", str(tmp_path))
    return tmp_path


def runner(client: Script, tools: Tools | None = None, **kwargs: Any) -> subagents.Runner:
    return subagents.Runner(client, schemas, tools or Tools(), **kwargs)


def finished(run: subagents.Runner, answer: dict[str, Any]) -> dict[str, Any]:
    assert answer["ok"], answer
    run.wait(answer["id"], 5)
    return run.status(answer["id"])


def test_only_the_final_report_comes_back(root) -> None:
    client = Script(reply(calls=[call("web_search", query="x")]), reply("Found it: the key was unset."))
    tools = Tools(web_search={"status": "executed", "result": {"secret_page": "long intermediate output"}})
    run = runner(client, tools)

    job = finished(run, run.start("worker", "find why the key is unset"))

    assert job["state"] == "completed" and job["exit_reason"] == "completed"
    assert job["summary"] == "Found it: the key was unset."
    assert "long intermediate output" not in str(job)
    assert tools.names() == ["web_search"]
    # The second round saw the tool's answer, as a proper tool message.
    assert any(m.get("role") == "tool" for m in client.calls[1][0])


def test_offered_tools_are_the_definition_less_what_marvi_keeps(root) -> None:
    client = Script(reply("ok"), reply("ok"))
    run = runner(client)

    finished(run, run.start("jarvi", "open notepad"))
    finished(run, run.start("worker", "sort the downloads"))

    assert client.offered(0) == {"computer_status", "computer_action", "todo_write"}
    worker = client.offered(1)
    assert {"web_search", "file_read", "todo_write"} <= worker
    assert not worker & {"memory_remember", "telegram_send", "delegate", "clarify"}
    # The desktop and the browser are Jarvi's and Talos's; a worker driving
    # them too would fight a running Jarvi for the same screen.
    assert not worker & {"computer_action", "browser_action"}


def test_a_blocked_tool_is_refused_even_when_called_by_name(root) -> None:
    client = Script(reply(calls=[call("telegram_send", text="hi")]), reply("could not"))
    tools = Tools()
    run = runner(client, tools)

    finished(run, run.start("worker", "tell them"))

    assert tools.names() == []
    said = [m for m in client.calls[1][0] if m.get("role") == "tool"][0]["content"]
    assert "not available" in said


def test_the_last_round_offers_no_tools(root, monkeypatch) -> None:
    monkeypatch.setattr(subagents, "DEFAULT_ROUNDS", 2)
    client = Script(
        reply(calls=[call("web_search", query="a")]),
        reply(calls=[call("web_search", query="b")]),
        reply("Here is what I have so far."),
    )
    run = runner(client)

    job = finished(run, run.start("worker", "research", rounds=2))

    assert client.calls[-1][1]["tools"] is None
    assert job["exit_reason"] == "max_rounds"
    assert job["summary"] == "Here is what I have so far."


def test_three_identical_failures_end_the_job(root) -> None:
    same = call("web_search", query="x")
    client = Script(*[reply(calls=[dict(same)]) for _ in range(5)])
    tools = Tools(web_search={"status": "failed", "error": "search backend down"})
    run = runner(client, tools)

    job = finished(run, run.start("worker", "look it up"))

    assert job["state"] == "failed" and job["exit_reason"] == "error"
    assert "search backend down" in job["summary"]
    assert len(tools.seen) == 3


def test_stop_interrupts_a_running_job(root) -> None:
    release = threading.Event()

    def slow(_messages):
        release.wait(5)
        return reply(calls=[call("web_search", query="x")])

    client = Script(slow)
    run = runner(client)
    started = run.start("worker", "long job")
    assert run.stop(started["id"])["ok"]
    release.set()

    job = finished(run, started)
    assert job["state"] == "interrupted" and job["exit_reason"] == "stopped"


def test_stopping_mid_round_sends_nothing_further(root) -> None:
    """Stop does not pause the computer; it stops this job issuing actions.
    The call in flight finishes; the ones queued behind it in the round do not
    reach the desktop."""
    client = Script(
        reply(calls=[call("computer_action", action="click"), call("computer_action", action="type_text")])
    )
    seen: list[str] = []
    known = threading.Event()
    holder: dict[str, str] = {}

    def tools(name, arguments):
        known.wait(5)
        seen.append(arguments["action"])
        run.stop(holder["id"])
        return {"status": "executed", "result": {}}

    run = runner(client, tools)
    started = run.start("jarvi", "click then type")
    holder["id"] = started["id"]
    known.set()
    run.wait(started["id"], 5)

    assert seen == ["click"]
    assert run.status(started["id"])["state"] == "interrupted"


def test_steering_reaches_the_next_round(root) -> None:
    holder: dict[str, str] = {}
    known = threading.Event()

    def first(_messages):
        known.wait(5)
        subagents_run.steer(holder["id"], "only the Python files")
        return reply(calls=[call("web_search", query="x")])

    client = Script(first, reply("ok"))
    subagents_run = runner(client)
    answer = subagents_run.start("worker", "count lines")
    holder["id"] = answer["id"]
    known.set()
    finished(subagents_run, answer)

    seen = " ".join(str(m.get("content")) for m in client.calls[1][0])
    assert "only the Python files" in seen


def test_concurrency_is_capped_and_one_desktop_is_one_jarvi(root) -> None:
    release = threading.Event()
    client = Script(*[lambda _m: (release.wait(5), reply("ok"))[1] for _ in range(4)])
    run = runner(client)

    first = run.start("jarvi", "a")
    assert first["ok"]
    second = run.start("jarvi", "b")
    assert not second["ok"] and "Jarvi" in second["detail"]
    assert run.start("worker", "c")["ok"]
    assert run.start("worker", "d")["ok"]
    assert not run.start("worker", "e")["ok"]
    release.set()


def test_confirmation_parks_the_job_until_it_is_settled(root) -> None:
    (root / "a.txt").write_text("x", encoding="utf-8")
    client = Script(
        reply(calls=[call("file_read", path="a.txt")]),
        reply(calls=[call("file_edit", path="a.txt", old="x", new="y")]),
        reply("Changed it."),
    )
    tools = Tools(file_edit={"status": "confirmation_required", "token": "t1"})
    live = {"t1"}
    run = runner(client, tools, pending=lambda token: token in live)
    started = run.start("harvi", "change x to y", mode="fix")

    deadline = time.monotonic() + 5
    while run.status(started["id"])["state"] != "awaiting_approval":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    parked = run.status(started["id"])
    assert parked["token"] == "t1" and "file_edit" in parked["action"]
    assert "delegate_approve" in parked["detail"]

    live.clear()
    run.settling("t1")
    run.settled("t1", {"status": "executed", "result": {"changed": True}})

    job = finished(run, started)
    assert job["state"] == "completed"
    said = [m for m in client.calls[2][0] if m.get("role") == "tool"][-1]["content"]
    assert "changed" in said


def test_a_denied_action_is_reported_to_the_sub_agent(root) -> None:
    client = Script(reply(calls=[call("web_search", query="x")]), reply("They said no."))
    tools = Tools(web_search={"status": "confirmation_required", "token": "t2"})
    run = runner(client, tools, pending=lambda _t: True)
    started = run.start("worker", "x")
    deadline = time.monotonic() + 5
    while run.status(started["id"])["state"] != "awaiting_approval":
        assert time.monotonic() < deadline
        time.sleep(0.01)

    run.settled("t2", {"status": "denied"})

    finished(run, started)
    said = [m for m in client.calls[1][0] if m.get("role") == "tool"][-1]["content"]
    assert "denied" in said


def test_an_expired_confirmation_does_not_run(root, monkeypatch) -> None:
    monkeypatch.setattr(subagents, "APPROVAL_GRACE", 0.05)
    client = Script(reply(calls=[call("web_search", query="x")]), reply("Nobody answered."))
    tools = Tools(web_search={"status": "confirmation_required", "token": "t3"})
    run = runner(client, tools, pending=lambda _t: False)

    finished(run, run.start("worker", "x"))

    said = [m for m in client.calls[1][0] if m.get("role") == "tool"][-1]["content"]
    assert "expired" in said


def test_investigate_is_read_only(root) -> None:
    client = Script(reply("It is the config."))
    run = runner(client)

    finished(run, run.start("harvi", "why is it broken"))

    offered = client.offered(0)
    assert {"file_read", "grep", "glob"} <= offered
    assert not offered & {"file_edit", "file_write", "file_delete"}


def test_an_edit_is_refused_until_the_file_is_read(root) -> None:
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    client = Script(
        reply(calls=[call("file_edit", path="a.py", old="1", new="2")]),
        reply(calls=[call("file_read", path="a.py")]),
        reply(calls=[call("file_edit", path="a.py", old="1", new="2")]),
        reply("Done."),
    )
    tools = Tools()
    run = runner(client, tools)

    finished(run, run.start("harvi", "set x to 2", mode="fix"))

    assert tools.names() == ["file_read", "file_edit"]
    first = [m for m in client.calls[1][0] if m.get("role") == "tool"][0]["content"]
    assert "Read a.py" in first


def test_a_fix_job_edits_under_the_approval_it_was_started_with(root) -> None:
    """`delegate(harvi, fix)` is the one confirmation; its edits and commands
    under the workspace do not each ask again. Anything else still does."""
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    client = Script(
        reply(calls=[call("file_read", path="a.py")]),
        reply(calls=[call("file_edit", path="a.py", old="1", new="2")]),
        reply(calls=[call("terminal_run", command="pytest")]),
        reply(calls=[call("web_search", query="q")]),
        reply("ok"),
    )
    asked, granted = Tools(), Tools()
    run = runner(client, asked, granted=granted)

    finished(run, run.start("harvi", "set x to 2", mode="fix"))

    assert granted.names() == ["file_edit", "terminal_run"]
    assert asked.names() == ["file_read", "web_search"]


def test_investigate_has_no_grant(root) -> None:
    client = Script(reply(calls=[call("terminal_run", command="git status")]), reply("ok"))
    asked, granted = Tools(), Tools()
    run = runner(client, asked, granted=granted)

    finished(run, run.start("harvi", "look"))

    assert granted.names() == [] and asked.names() == ["terminal_run"]


def test_a_new_file_needs_no_read(root) -> None:
    client = Script(reply(calls=[call("file_write", path="new.py", content="x")]), reply("ok"))
    tools = Tools()
    run = runner(client, tools)

    finished(run, run.start("harvi", "create it", mode="fix"))

    assert tools.names() == ["file_write"]


def test_todo_write_is_the_progress_line(root) -> None:
    todos = [
        {"content": "Reproduce the failure", "status": "completed"},
        {"content": "Fix the import", "status": "in_progress"},
    ]
    client = Script(reply(calls=[call("todo_write", todos=todos)]), reply("ok"))
    seen: list[str] = []

    def peek(_messages):
        seen.append(run.status()["jobs"][0]["progress"])
        return reply("ok")

    client.replies[1] = peek
    run = runner(client)
    answer = run.start("harvi", "fix it", mode="fix")
    finished(run, answer)

    assert seen == ["Fix the import"]


def test_a_stalled_job_is_ended(root, monkeypatch) -> None:
    monkeypatch.setattr(subagents, "STALL_SECONDS", 0.05)
    monkeypatch.setattr(subagents, "WATCH_EVERY", 0.02)
    release = threading.Event()
    client = Script(lambda _m: (release.wait(5), reply("late"))[1])
    run = runner(client)
    started = run.start("worker", "x")

    deadline = time.monotonic() + 5
    while run.status(started["id"])["state"] == "running":
        assert time.monotonic() < deadline
        time.sleep(0.02)
    release.set()

    job = run.status(started["id"])
    assert job["state"] == "failed" and job["exit_reason"] == "stalled"


def test_the_island_can_name_who_is_using_the_computer(root) -> None:
    release = threading.Event()
    run = runner(Script(lambda _m: (release.wait(5), reply("ok"))[1]))
    assert run.acting("jarvi") == ""

    started = run.start("jarvi", "open notepad")
    assert run.acting("jarvi") == "Jarvi"
    release.set()
    run.wait(started["id"], 5)
    assert run.acting("jarvi") == ""


def test_computer_status_carries_the_actor() -> None:
    from marvi_gateway.computer import ComputerUse

    service = ComputerUse(None)
    assert service.status()["actor"] == ""
    service.actor = lambda: "Jarvi"
    assert service.status()["actor"] == "Jarvi"


def test_a_long_tool_is_not_a_stall(root, monkeypatch) -> None:
    """A test suite in the foreground may run ten minutes. Inside a tool the
    patience is longer, as Hermes's is: 1,200 seconds against 450."""
    monkeypatch.setattr(subagents, "STALL_SECONDS", 0.05)
    monkeypatch.setattr(subagents, "STALL_IN_TOOL", 5.0)
    monkeypatch.setattr(subagents, "WATCH_EVERY", 0.02)
    client = Script(reply(calls=[call("web_search", query="x")]), reply("done"))

    def slow_tool(name, arguments):
        time.sleep(0.3)
        return {"status": "executed", "result": {}}

    run = runner(client, slow_tool)
    job = finished(run, run.start("worker", "x"))

    assert job["state"] == "completed"


def test_bad_requests_are_refused(root) -> None:
    run = runner(Script())
    assert not run.start("nobody", "x")["ok"]
    assert not run.start("worker", "   ")["ok"]
    assert not run.start("harvi", "x", mode="yolo")["ok"]
    assert not run.status("nope")["ok"]


def test_harvi_is_harvi_and_a_worker_gets_a_name(root) -> None:
    run = runner(Script(reply("ok"), reply("ok")))
    harvi = run.start("harvi", "x")
    worker = run.start("worker", "y")
    assert harvi["name"] == "Harvi"
    assert worker["name"] and worker["name"] != "worker"
    assert worker["name"] in worker["detail"]


def test_harvi_is_briefed_with_the_root_and_mode(root) -> None:
    client = Script(reply("ok"))
    run = runner(client)

    finished(run, run.start("harvi", "why", mode="investigate"))

    system = client.calls[0][0][0]["content"]
    assert "You are Harvi" in system
    assert str(root) in system and "Mode: investigate" in system


def test_the_tools_are_registered_and_described(root) -> None:
    registry = ToolRegistry()
    run = runner(Script())
    subagents.register_subagent_tools(registry, run)

    names = {spec.name for spec in registry}
    assert {"delegate", "delegate_stop", "delegate_steer", "delegate_approve", "delegated_status"} <= names
    delegate = registry.get("delegate")
    # Only letting Harvi change code is the owner's call; everything else is
    # confirmed action by action inside the job.
    assert not delegate.is_sensitive({"agent": "jarvi", "task": "x"})
    assert not delegate.is_sensitive({"agent": "harvi", "task": "x", "mode": "investigate"})
    assert delegate.is_sensitive({"agent": "harvi", "task": "x", "mode": "fix"})
    assert len(delegate.description) >= 120
    for agent in ("harvi", "jarvi", "talos", "worker"):
        assert agent in delegate.describes["agent"]


def _gateway_with_a_sensitive_tool(tmp_path):
    from marvi_gateway.app import create_app
    from marvi_gateway.runtime import RuntimeStore
    from marvi_gateway.tools import ToolSpec

    ran: list[dict[str, Any]] = []
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            name="room_set_mode",
            description="Turn off the room light",
            arguments={"mode": str},
            sensitive=True,
            handler=lambda **args: ran.append(args) or {"mode": args["mode"], "done": True},
        )
    )
    app = create_app(
        version="0.1.0-test", runtime=RuntimeStore(audit_path=tmp_path / "audit.jsonl"), tools=tools
    )
    run: subagents.Runner = app.state.subagents
    subagents.register_subagent_tools(tools, run)
    return app, run, ran


async def _parked(run: subagents.Runner, job_id: str) -> dict[str, Any]:
    import asyncio

    for _ in range(500):
        job = run.status(job_id)
        if job["state"] == "awaiting_approval":
            return job
        await asyncio.sleep(0.01)
    raise AssertionError(f"never parked: {run.status(job_id)}")


@pytest.mark.asyncio
async def test_the_island_approves_what_a_sub_agent_asked_for(root, tmp_path) -> None:
    """The real Gateway path: the sub-agent's call issues a real token, the
    Island's `/confirmations` answer runs the action, and the waiting job is
    handed that result rather than running it twice."""
    from httpx import ASGITransport, AsyncClient

    app, run, ran = _gateway_with_a_sensitive_tool(tmp_path)
    run.client = Script(reply(calls=[call("room_set_mode", mode="off")]), reply("The light is off."))

    started = run.start("worker", "turn the light off")
    job = await _parked(run, started["id"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://marvi.local") as client:
        answer = await client.post(
            f"/confirmations/{job['token']}",
            json={"decision": "approve", "arguments": {"mode": "off"}},
        )
    assert answer.json()["status"] == "executed"

    run.wait(started["id"], 5)
    assert ran == [{"mode": "off"}]
    assert run.status(started["id"])["summary"] == "The light is off."
    said = [m for m in run.client.calls[1][0] if m.get("role") == "tool"][-1]["content"]
    assert '"done": true' in said


@pytest.mark.asyncio
async def test_marvi_relays_a_spoken_no(root, tmp_path) -> None:
    from httpx import ASGITransport, AsyncClient

    app, run, ran = _gateway_with_a_sensitive_tool(tmp_path)
    run.client = Script(reply(calls=[call("room_set_mode", mode="off")]), reply("Left it on."))

    started = run.start("worker", "turn the light off")
    await _parked(run, started["id"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://marvi.local") as client:
        answer = await client.post(
            "/tools/delegate_approve",
            json={"arguments": {"job": started["id"], "approve": False}},
        )
    assert answer.json()["result"]["status"] == "denied"

    run.wait(started["id"], 5)
    assert ran == []
    said = [m for m in run.client.calls[1][0] if m.get("role") == "tool"][-1]["content"]
    assert "denied" in said


def test_delegated_status_still_finds_outside_coder_jobs(root, monkeypatch) -> None:
    from marvi_gateway import delegate

    registry = ToolRegistry()
    subagents.register_subagent_tools(registry, runner(Script()))
    monkeypatch.setattr(delegate, "status", lambda job="": {"ok": True, "id": job, "coder": "codex"})

    answer = registry.get("delegated_status").handler(job="abc")
    assert answer["coder"] == "codex"


def test_harvi_reads_the_coding_harness_and_voice_does_not() -> None:
    """Claude Code's coding rules go to the coder, not to every voice turn.

    Its shell tool alone is thirty-seven fragments -- git safety, quoting,
    background runs, the commit and pull-request protocols. A coding agent
    needs all of it. The voice agent would pay for it on every request and use
    none of it, which is the payload problem deferral was built to solve.
    """
    from marvi_gateway import prompts

    prompts.forget()
    assert prompts.get("harvi").tool_descriptions == "coding"

    for tool in ("terminal_run", "file_read", "file_edit", "file_write", "grep", "glob"):
        coding = prompts.tool(tool, variant="coding")
        shared = prompts.tool(tool)
        assert coding and shared, tool
        assert coding != shared, f"{tool}: the coding set is not being read"

    shell = prompts.tool("terminal_run", variant="coding")
    for rule in ("NEVER change the git config", "Prefer a NEW commit", "gh pr create",
                 "background", "Use a dedicated tool"):
        assert rule in shell, f"missing from the coding shell description: {rule!r}"


def test_the_shared_descriptions_stay_short_for_voice() -> None:
    """The coding set must not leak into what every other surface is sent."""
    from marvi_gateway import prompts

    prompts.forget()
    assert len(prompts.tool("terminal_run")) < 1500
    # `tools()` is non-recursive, so the coding folder is never mistaken for
    # shared tools named `coding/...`.
    assert not any("/" in name or "\\" in name for name in prompts.tools())


def test_the_ported_descriptions_use_marvis_argument_names() -> None:
    """Ported text, not copied text.

    Claude Code's tools take `old_string`, `new_string`, `file_path` and
    `run_in_background`. Marvi's take `old`, `new`, `path` and `background`. A
    description naming an argument the tool does not have is worse than no
    description: the model sends it, the call is refused, and the refusal
    blames the model for following instructions.
    """
    from marvi_gateway import prompts

    for tool in ("terminal_run", "file_read", "file_edit", "file_write", "grep", "glob",
                 "process_output"):
        said = prompts.tool(tool, variant="coding")
        for foreign in ("old_string", "new_string", "file_path", "run_in_background"):
            assert foreign not in said, f"{tool} still names Claude Code's {foreign!r}"


def test_what_harvi_is_actually_handed_carries_the_coding_rules() -> None:
    """The integration point, not the lookup: `_offered` is what Harvi sees."""
    from types import SimpleNamespace

    from marvi_gateway import prompts

    prompts.forget()
    run = runner(Script([]))
    job = SimpleNamespace(mode="fix")

    handed = {s["name"]: s["description"] for s in run._offered(job, prompts.get("harvi"))}
    assert "NEVER change the git config" in handed["terminal_run"]
    assert "must `file_read` the file" in handed["file_edit"]

    # Jarvi drives the desktop, reads the shared set, and is not sent git rules.
    jarvi = {s["name"]: s["description"] for s in run._offered(job, prompts.get("jarvi"))}
    for name, said in jarvi.items():
        assert "git config" not in said, name


# -- the feed the desktop reads ------------------------------------------------


def test_a_job_keeps_a_short_live_transcript(root) -> None:
    """What the owner sees when they open a working agent: what it said, each
    step and whether it worked, its list, and how it ended. Never what a tool
    returned -- that is untrusted, and it can be a whole web page."""
    todos = [{"content": "Open the app", "status": "in_progress"}, {"content": "Read it", "status": "pending"}]
    client = Script(
        reply("Starting with the file.", calls=[call("todo_write", todos=todos)]),
        reply(calls=[call("file_write", path="notes.txt", content="a secret-looking body " * 20)]),
        reply(calls=[call("web_search", query="x")]),
        reply("All done."),
    )
    tools = Tools(web_search={"status": "failed", "error": "offline"},
                  file_write={"status": "executed", "result": {"page": "RAW TOOL OUTPUT"}})
    run = runner(client, tools)

    job = finished(run, run.start("worker", "write the notes"))
    detail = run.job(job["id"])

    kinds = [event["kind"] for event in detail["events"]]
    assert kinds == ["said", "tool", "tool", "tool", "end"]
    said = " ".join(event["text"] for event in detail["events"])
    assert "Starting with the file." in said and "All done." in said
    assert "RAW TOOL OUTPUT" not in said
    # A long body is described, not reproduced.
    write = detail["events"][2]
    assert write["text"].startswith("file_write") and "notes.txt" in write["text"]
    assert "secret-looking" not in write["text"] and "440 chars" in write["text"]
    assert [event.get("outcome") for event in detail["events"][1:4]] == ["ok", "ok", "failed"]
    assert detail["todos"] == todos


def test_the_transcript_is_bounded(root, monkeypatch) -> None:
    monkeypatch.setattr(subagents, "MAX_EVENTS", 5)
    client = Script(*[reply(calls=[call("web_search", query=str(i))]) for i in range(8)], reply("ok"))
    run = runner(client)

    job = finished(run, run.start("worker", "x"))

    events = run.job(job["id"])["events"]
    assert len(events) == 5 and events[-1]["kind"] == "end"


def test_the_feed_waits_for_a_change_rather_than_being_polled(root) -> None:
    """Idle, the desktop's request waits; a change answers it at once."""
    release = threading.Event()
    run = runner(Script(lambda _m: (release.wait(5), reply("ok"))[1]))
    first = run.watch(None)
    # The built-ins first; installed outside coders follow them.
    assert [agent["key"] for agent in first["agents"]][:4] == ["harvi", "jarvi", "talos", "worker"]
    assert first["agents"][0]["name"] == "Harvi" and first["agents"][0]["description"]

    started = time.monotonic()
    idle = run.watch(first["revision"], timeout=0.2)
    assert idle["revision"] == first["revision"] and time.monotonic() - started >= 0.18

    answer: dict[str, Any] = {}
    waiter = threading.Thread(target=lambda: answer.update(run.watch(first["revision"], timeout=5)))
    waiter.start()
    run.start("jarvi", "open notepad")
    waiter.join(5)
    assert answer["revision"] > first["revision"]
    assert answer["jobs"][0]["name"] == "Jarvi" and "events" not in answer["jobs"][0]
    release.set()


def test_an_unknown_job_is_said_to_be_unknown(root) -> None:
    run = runner(Script())
    assert run.job("gone") is None


@pytest.mark.asyncio
async def test_the_desktop_endpoints_need_the_local_token(root, tmp_path, monkeypatch) -> None:
    from httpx import ASGITransport, AsyncClient

    app, run, _ = _gateway_with_a_sensitive_tool(tmp_path)
    run.client = Script(lambda _m: (time.sleep(0.2), reply("ok"))[1])
    started = run.start("worker", "x")
    monkeypatch.setenv("MARVI_LOCAL_TOKEN", "desk")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://marvi.local") as client:
        refused = await client.get("/agents")
        feed = await client.get("/agents", headers={"x-marvi-local": "desk"})
        job = await client.get(f"/agents/jobs/{started['id']}", headers={"x-marvi-local": "desk"})
        missing = await client.get("/agents/jobs/nope", headers={"x-marvi-local": "desk"})
        stopped = await client.post(f"/agents/jobs/{started['id']}/stop", headers={"x-marvi-local": "desk"})

    assert refused.status_code == 403
    assert feed.status_code == 200 and feed.json()["jobs"][0]["id"] == started["id"]
    assert job.json()["id"] == started["id"] and "events" in job.json()
    assert missing.status_code == 404
    assert stopped.json()["ok"] is True
    run.wait(started["id"], 5)


def test_marvi_is_pointed_at_the_specialists_and_they_are_not() -> None:
    """Marvi holds the conversation; Jarvi and Talos do the long work.

    A desktop demo run in Marvi's own turn took seven rounds and exhausted her
    tool budget. So her view of these tools is short and says to delegate --
    and the specialists, who read the same tool names, get the full operating
    descriptions instead of being told to hand the work to themselves.
    """
    from marvi_gateway import prompts

    prompts.forget()
    for tool, specialist, variant in (
        ("computer_action", "Jarvi", "desktop"),
        ("browser_action", "Talos", "browser"),
    ):
        mine = prompts.tool(tool)
        theirs = prompts.tool(tool, variant=variant)
        assert f"hand it to {specialist}" in mine, tool
        assert "delegate" in mine, tool
        assert "hand it to" not in theirs, f"{specialist} would be told to delegate to itself"

    assert prompts.get("jarvi").tool_descriptions == "desktop"
    assert prompts.get("talos").tool_descriptions == "browser"


def test_no_specialist_is_offered_a_tool_that_tells_it_to_delegate() -> None:
    """The fallback to the shared set must never reach a specialist's own tools."""
    from types import SimpleNamespace

    from marvi_gateway import prompts

    prompts.forget()
    run = runner(Script([]))
    job = SimpleNamespace(mode="fix")
    for agent in ("jarvi", "talos", "harvi"):
        for schema in run._offered(job, prompts.get(agent)):
            assert "hand it to" not in schema["description"], f"{agent}: {schema['name']}"
