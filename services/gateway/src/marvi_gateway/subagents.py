"""Sub-agents: work Marvi hands off so the conversation does not stop for it.

The voice model used to drive the desktop itself. Cua's look, act and check
loop is a second or more per step -- launch 4.5 s, observation 1.7 s, click
1.3 s on the Phase 15 fixture -- so ten steps held one spoken turn for half a
minute, and Marvi could not be talked to until it ended. The coding harness had
the opposite problem: `delegate.py` hands a job to someone else's CLI, and
`prompts/coding-agent.md` was written for "Marvi's own coding sub-agent" that
did not exist.

A sub-agent is the same thing Cron and Cognition already run -- a small tool
loop over `ProviderClient` and the Gateway's audited dispatch -- with its own
message list, on its own thread, started by `delegate` and answered later
through the `delegated.py` seam voice already has.

## Who they are

`prompts/harvi.md`, `jarvi.md`, `talos.md` and `worker.md`. A prompt with a
`when-to-use` is an agent and one that also declares `tools` is one this can
run; the file is the whole definition, so what Marvi reads when routing and
what the sub-agent is told cannot drift apart. Harvi codes, Jarvi drives
applications, Talos drives the browser, and a worker takes anything else under
a name drawn for the run.

## The contract

Taken from Hermes Agent's `delegate_task` (MIT), whose documented behaviour it
follows rather than whose code it copies -- that code is bound to Hermes's own
agent class:

* **A fresh context.** The job sees its task and its prompt, never the
  conversation. Marvi writes the task for someone who was not there.
* **Only the report comes back.** Intermediate tool output stays in the job;
  voice is handed a few sentences, not a transcript.
* **Marvi keeps some tools.** `BLOCKED` is withheld from every sub-agent and
  refused by name if one is called anyway: memory, messages, schedules,
  questions to the owner, and delegation itself -- no nesting.
* **Nothing holds a job forever.** A last round with no tools, so running out
  still produces a report; three identical failures end it; so does silence
  past `STALL_SECONDS`; and Marvi can stop or steer it.

## Confirmation

The Gateway's own path, unchanged. A tool that needs confirmation parks the job
as `awaiting_approval`; that is pushed to Marvi like a finished job, she asks,
and whichever surface settles the token -- the Island, a spoken yes through
`delegate_approve`, Telegram -- tells the runner what happened. A token that
expires unanswered is reported to the sub-agent as not having run.

One exception, and it is the old one: approving `delegate(harvi, mode=fix)`
approves that job's edits and commands under the workspace root, exactly as
approving `codex --sandbox workspace-write` did. Asking again for every line
Harvi changes would make Confirm mode unusable for the one thing fix mode is.
Everything else inside the job is still confirmed action by action.

Jobs live in memory, as `delegate.py`'s do. A restart loses the record, not the
work: that is on disk and in git. Phase 17 makes the record durable.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import acp_coders, prompts, tool_call_prose
from .chat_widgets import external_text
from .logs import get_logger
from .untrusted import wrap_external
from .workspace import default_root

log = get_logger("subagents")

#: Tools Marvi keeps for herself. A sub-agent reports; she acts on the report.
#: The description sets written for someone who does the work rather than
#: hands it on. See `_offered`.
OPERATING = ("coding", "desktop", "browser")

BLOCKED = frozenset(
    {
        "delegate", "delegate_stop", "delegate_steer", "delegate_approve",
        "delegate_to_coder", "await_delegated",
        "memory_remember", "memory_forget", "note_about_user",
        "telegram_send", "send_email",
        "speak", "end_conversation",
        "cronjob", "schedule_add",
        "clarify", "ask_secret",
    }
)

#: More than this at once is a queue, and a queue is Phase 17.
MAX_RUNNING = 3
#: One desktop and one visible browser: two of either would fight over it.
SINGLE = frozenset({"jarvi", "talos"})
#: No model answer and no tool result for this long means stuck.
STALL_SECONDS = 450.0
#: Inside one tool call the patience is longer: a foreground test suite may
#: legitimately run `terminal_run`'s full ten minutes. Hermes's numbers.
STALL_IN_TOOL = 1200.0
WATCH_EVERY = 15.0
#: How long a vanished confirmation token may stay unexplained before it is
#: read as expired. Approval paths mark a token `settling` the moment they take
#: it, so this only has to cover that instant.
APPROVAL_GRACE = 2.0
DEFAULT_ROUNDS = 25
REPEATS = 3
MAX_TASK = 8_000
MAX_RESULT = 8_000
#: The live transcript the desktop shows, per job: the most recent steps only.
MAX_EVENTS = 60
#: Jobs the desktop feed lists, newest first. Older ones stay in memory and
#: answer `delegated_status` until a restart.
MAX_LISTED = 20
#: How long a desktop request waits for something to change, as `/computer` does.
WATCH_TIMEOUT = 25.0
MODES = ("investigate", "fix")
#: What investigate mode takes away from Harvi.
WRITES = frozenset({"file_write", "file_edit", "file_delete"})
#: What an approved fix job may run without asking again.
GRANTED = frozenset({"file_write", "file_edit", "file_delete", "terminal_run"})

TODO_WRITE = {
    "name": "todo_write",
    "description": (
        "Keep this job's task list. Send the whole list every time: each item has "
        "`content` and a `status` of pending, in_progress or completed. Keep exactly "
        "one item in_progress -- it is the status line the owner sees -- and mark "
        "each completed the moment it is. Use it for jobs of three or more steps, "
        "not for a single step."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                    },
                    "required": ["content", "status"],
                },
            }
        },
        "required": ["todos"],
    },
}


@dataclass
class Job:
    id: str
    agent: str
    name: str
    task: str
    mode: str
    rounds: int
    state: str = "running"
    exit_reason: str = ""
    summary: str = ""
    progress: str = ""
    token: str = ""
    action: str = ""
    tokens: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    active: float = field(default_factory=time.monotonic)
    in_tool: bool = False
    read: set[str] = field(default_factory=set)
    #: What the owner sees when they open this job: the agent's own words,
    #: each step and whether it worked, approvals, and the ending. Never a
    #: tool's result -- that is untrusted, and it can be a whole page.
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    todos: list[dict[str, str]] = field(default_factory=list)
    steering: list[str] = field(default_factory=list)
    stop: threading.Event = field(default_factory=threading.Event)
    answered: threading.Event = field(default_factory=threading.Event)
    outcome: dict[str, Any] = field(default_factory=dict)
    thread: threading.Thread | None = None

    @property
    def live(self) -> bool:
        return self.state in ("running", "awaiting_approval")

    def detail(self) -> str:
        if self.state == "running":
            return f"{self.name} is on it, job {self.id}" + (f" -- {self.progress}" if self.progress else "")
        if self.state == "awaiting_approval":
            return (
                f"{self.name} wants to run {self.action} and is waiting. Ask the owner, then call "
                f"delegate_approve with job {self.id} and approve true or false."
            )
        if self.state == "completed":
            return self.summary
        return f"{self.name} {self.state} ({self.exit_reason}): {self.summary}"

    def as_dict(self) -> dict[str, Any]:
        answer: dict[str, Any] = {
            "ok": True,
            "id": self.id,
            "agent": self.agent,
            "name": self.name,
            "mode": self.mode,
            "task": self.task[:200],
            "state": self.state,
            "exit_reason": self.exit_reason,
            "summary": self.summary,
            "progress": self.progress,
            "seconds": round((self.finished_at or time.time()) - self.started_at, 1),
            "started_at": self.started_at,
            "finished_at": self.finished_at or None,
            "tokens": self.tokens,
            "detail": self.detail(),
        }
        if self.state == "awaiting_approval":
            answer.update(token=self.token, action=self.action)
        return answer


def _step(name: str, arguments: dict[str, Any]) -> str:
    """One tool call as a line for the owner: the tool, and short arguments.

    A long value is described by its length rather than shown. A file body or
    typed text belongs in the file, not in a status panel, and the ones worth
    reading at a glance -- a path, an action, a query -- are short.
    """
    parts = []
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > 60:
            parts.append(f"{key}=<{len(value)} chars>")
        elif isinstance(value, (list, dict)):
            parts.append(f"{key}=<{len(value)} items>")
        else:
            parts.append(f"{key}={value}")
    return (f"{name} " + ", ".join(parts))[:160].strip()


def _arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}") if isinstance(raw, str) else {}
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class Runner:
    """Starts, follows, stops and settles sub-agent jobs."""

    def __init__(
        self,
        client: Any,
        schemas: Callable[[], list[dict[str, Any]]],
        dispatch: Callable[[str, dict[str, Any]], dict[str, Any]],
        pending: Callable[[str], bool] | None = None,
        settle: Callable[[str, bool], dict[str, Any]] | None = None,
        granted: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        prompts_root: Path | None = None,
    ) -> None:
        self.client = client
        self.schemas = schemas
        self.dispatch = dispatch
        #: Whether a confirmation token is still waiting for an answer.
        self.pending = pending or (lambda _token: True)
        #: Consumes a token and runs or refuses its action, for `delegate_approve`.
        self.settle = settle
        #: Dispatch without a fresh confirmation, for an approved fix job.
        self.granted = granted or dispatch
        self.prompts_root = prompts_root
        self._jobs: dict[str, Job] = {}
        self._waiting: dict[str, Job] = {}
        self._settling: set[str] = set()
        self._lock = threading.Lock()
        self._watching = False
        #: Bumped on every change the desktop can see; `watch` waits on it.
        self._changed = threading.Condition()
        self._revision = 0

    # -- definitions -------------------------------------------------------

    def agents(self) -> list[prompts.Prompt]:
        return [one for one in prompts.agents(self.prompts_root) if one.runnable]

    def _definition(self, agent: str) -> prompts.Prompt | None:
        return next((one for one in self.agents() if one.key == agent), None)

    # -- starting ----------------------------------------------------------

    def start(self, agent: str, task: str, mode: str = "", rounds: int = 0) -> dict[str, Any]:
        agent = (agent or "").strip().lower()
        task = (task or "").strip()
        if agent in acp_coders.CODERS:
            return self._start_outside(acp_coders.CODERS[agent], task, mode)
        definition = self._definition(agent)
        if definition is None:
            known = ", ".join(one.key for one in self.agents())
            return {"ok": False, "detail": f"no sub-agent called {agent!r}; there is {known}"}
        if not task:
            return {"ok": False, "detail": "nothing to hand over"}
        if len(task) > MAX_TASK:
            return {"ok": False, "detail": f"that task is longer than {MAX_TASK} characters"}
        mode = (mode or "").strip().lower()
        if agent == "harvi":
            mode = mode or "investigate"
            if mode not in MODES:
                return {"ok": False, "detail": "Harvi's mode is investigate or fix"}
        else:
            mode = ""

        root = default_root()
        if agent == "harvi" and root is None:
            return {
                "ok": False,
                "detail": (
                    "no workspace root is configured, so there is nowhere Harvi is allowed "
                    "to work. Set MARVI_WORKSPACE_ROOT."
                ),
            }

        with self._lock:
            live = [job for job in self._jobs.values() if job.live]
            if agent in SINGLE and any(job.agent == agent for job in live):
                busy = next(job for job in live if job.agent == agent)
                return {
                    "ok": False,
                    "detail": f"{busy.name} is already working, job {busy.id}; stop it or wait",
                }
            if len(live) >= MAX_RUNNING:
                return {
                    "ok": False,
                    "detail": f"{len(live)} sub-agents are already working",
                    "running": [job.id for job in live],
                }
            taken = {job.name for job in live}
            free = [name for name in definition.names if name not in taken]
            name = random.choice(free or list(definition.names)) if definition.names else agent.title()
            job = Job(
                id=uuid.uuid4().hex[:8],
                agent=agent,
                name=name,
                task=task,
                mode=mode,
                rounds=max(1, rounds or definition.max_rounds or DEFAULT_ROUNDS),
            )
            self._jobs[job.id] = job
            self._watch()
        self._publish()

        system = definition.render()
        if agent == "harvi":
            system += "\n\n" + prompts.text("coding-agent", self.prompts_root, MODE=mode, ROOT=str(root))
        # Taken before the thread starts: the answer to `delegate` is "on it",
        # even for a job fast enough to have finished by the time it returns.
        answer = job.as_dict()
        job.thread = threading.Thread(
            target=self._run, args=(job, definition, system, root), daemon=True,
            name=f"marvi-subagent-{job.id}",
        )
        job.thread.start()
        log.info(
            "sub-agent started",
            extra={"marvi_job": job.id, "marvi_agent": agent, "marvi_mode": mode},
        )
        return answer

    def _start_outside(self, coder: acp_coders.Coder, task: str, mode: str) -> dict[str, Any]:
        """An outside coder's job: the same Job, run over ACP by `acp_coders`."""
        if not task:
            return {"ok": False, "detail": "nothing to hand over"}
        if len(task) > MAX_TASK:
            return {"ok": False, "detail": f"that task is longer than {MAX_TASK} characters"}
        mode = (mode or "investigate").strip().lower()
        if mode not in MODES:
            return {"ok": False, "detail": "mode is investigate or fix"}
        if not coder.command():
            return {
                "ok": False,
                "detail": f"{coder.name} is not installed",
                "available": [one.key for one in acp_coders.installed()],
            }
        root = default_root()
        if root is None:
            return {
                "ok": False,
                "detail": (
                    "no workspace root is configured, so there is nowhere a coding agent is "
                    "allowed to work. Set MARVI_WORKSPACE_ROOT."
                ),
            }
        with self._lock:
            live = [job for job in self._jobs.values() if job.live]
            if len(live) >= MAX_RUNNING:
                return {
                    "ok": False,
                    "detail": f"{len(live)} sub-agents are already working",
                    "running": [job.id for job in live],
                }
            job = Job(
                id=uuid.uuid4().hex[:8], agent=coder.key, name=coder.name, task=task,
                mode=mode, rounds=0,
            )
            self._jobs[job.id] = job
            self._watch()
        self._publish()
        # The standing brief every coder Marvi hands work to gets, then the task.
        prompt = (
            prompts.text("coding-agent", self.prompts_root, MODE=mode, ROOT=str(root))
            + "\n\n---\n\n# The task\n\n"
            + task
        )
        answer = job.as_dict()
        job.thread = threading.Thread(
            target=acp_coders.run, args=(self, job, coder, root, prompt), daemon=True,
            name=f"marvi-coder-{job.id}",
        )
        job.thread.start()
        log.info("outside coder started", extra={"marvi_job": job.id, "marvi_agent": coder.key, "marvi_mode": mode})
        return answer

    def ask_owner(self, job: Job, coder: str, kind: str, action: str) -> bool:
        """An outside coder's permission request, through Marvi's confirmation."""
        arguments = {"job": job.id, "coder": coder, "kind": kind, "action": action[:200]}
        outcome = self.dispatch("coder_permission", arguments)
        if outcome.get("status") == "confirmation_required":
            outcome = self._await_approval(job, f"{kind}:", {"action": action[:200]}, str(outcome.get("token") or ""))
        allowed = outcome.get("status") == "executed"
        self._note(job, "approval", f"{'allowed' if allowed else 'refused'} {kind}: {action[:120]}")
        return allowed

    def _offered(self, job: Job, definition: prompts.Prompt) -> list[dict[str, Any]]:
        allowed = set(definition.tools)

        def keep(name: str) -> bool:
            if name in BLOCKED or name in definition.denied_tools:
                return False
            if job.mode == "investigate" and name in WRITES:
                return False
            return "*" in allowed or name in allowed

        chosen = [schema for schema in self.schemas() if keep(str(schema.get("name")))]
        # The operating descriptions, never Marvi's.
        #
        # The shared set is Marvi's view, and for the desktop and the browser
        # it now says "hand it to Jarvi / Talos with delegate" -- which is
        # right for her and a dead end for every sub-agent, because `delegate`
        # is in BLOCKED. Harvi has every tool, so it was offered
        # `computer_action` and told to delegate something it cannot delegate.
        #
        # So a sub-agent reads its own set first, then whichever specialist
        # set describes the tool, and the shared one only when nobody has
        # written anything better.
        order = [definition.tool_descriptions] if definition.tool_descriptions else []
        order += [variant for variant in OPERATING if variant not in order]
        described = []
        for schema in chosen:
            name = str(schema["name"])
            said = next(
                (
                    text
                    for variant in order
                    if (text := prompts.tool(name, variant=variant, fallback=False))
                ),
                "",
            )
            described.append({**schema, "description": said} if said else schema)
        return [*described, TODO_WRITE]

    # -- the loop ----------------------------------------------------------

    def _run(self, job: Job, definition: prompts.Prompt, system: str, root: Path | None) -> None:
        offered = self._offered(job, definition)
        names = {str(schema["name"]) for schema in offered}
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": job.task},
        ]
        last_failure: tuple[str, str, str] | None = None
        repeats = 0
        try:
            for round_number in range(job.rounds + 1):
                if job.stop.is_set() or not job.live:
                    return self._end(job, "interrupted", "stopped", "stopped before it finished")
                with self._lock:
                    steering, job.steering = job.steering, []
                for note in steering:
                    messages.append({"role": "user", "content": f"Marvi adds: {note}"})

                final = round_number == job.rounds
                completion = self.client.call_with_fallback(
                    messages,
                    job=definition.model or "main",
                    tools=None if final else offered,
                )
                job.active = time.monotonic()
                job.tokens += completion.usage.billable
                if job.stop.is_set() or not job.live:
                    return self._end(job, "interrupted", "stopped", "stopped before it finished")

                calls = list(completion.tool_calls or [])
                if not calls and not final and (meant := tool_call_prose.recover(completion.text)):
                    calls = [{**meant, "id": f"recovered-{round_number}"}]
                if not calls:
                    report = completion.text.strip() or "It finished without saying anything."
                    return self._end(job, "completed", "max_rounds" if final else "completed", report)

                if completion.text.strip():
                    self._note(job, "said", completion.text.strip()[:300])
                ids = [str(one.get("id") or f"{job.id}-{round_number}-{i}") for i, one in enumerate(calls)]
                messages.append(
                    {
                        "role": "assistant",
                        "content": completion.text or None,
                        "tool_calls": [
                            {
                                "id": ids[i],
                                "type": "function",
                                "function": {
                                    "name": str(one.get("name") or ""),
                                    "arguments": json.dumps(_arguments(one.get("arguments"))),
                                },
                            }
                            for i, one in enumerate(calls)
                        ],
                    }
                )
                for i, one in enumerate(calls):
                    name = str(one.get("name") or "")
                    arguments = _arguments(one.get("arguments"))
                    step = self._note(job, "tool", _step(name, arguments), outcome="running")
                    job.active, job.in_tool = time.monotonic(), True
                    failed = True
                    try:
                        said, failed = self._tool(job, name, arguments, names, root)
                    finally:
                        job.active, job.in_tool = time.monotonic(), False
                        step["outcome"] = "failed" if failed else "ok"
                        self._publish()
                    messages.append(
                        {"role": "tool", "tool_call_id": ids[i], "name": name, "content": said}
                    )
                    if not failed:
                        last_failure, repeats = None, 0
                        continue
                    signature = (name, json.dumps(arguments, sort_keys=True, default=str), said)
                    repeats = repeats + 1 if signature == last_failure else 1
                    last_failure = signature
                    if repeats >= REPEATS:
                        return self._end(
                            job, "failed", "error",
                            f"{name} failed {REPEATS} times the same way: {said[:400]}",
                        )
            self._end(job, "completed", "max_rounds", "It ran out of steps without a report.")
        except Exception as exc:  # a provider or tool blowing up ends the job, not the Gateway
            log.warning("sub-agent failed", extra={"marvi_job": job.id, "marvi_error": str(exc)[:240]})
            self._end(job, "failed", "error", f"it stopped on an error: {str(exc)[:300]}")

    def _key(self, root: Path | None, path: str) -> Path | None:
        if not path:
            return None
        target = Path(path)
        if not target.is_absolute():
            if root is None:
                return None
            target = root / target
        return Path(os.path.normcase(os.path.abspath(target)))

    def _tool(
        self, job: Job, name: str, arguments: dict[str, Any], names: set[str], root: Path | None
    ) -> tuple[str, bool]:
        """Run one call. Returns what the sub-agent is told, and whether it failed."""
        if job.stop.is_set():
            # Stopping is not pausing the computer: an action already issued
            # finishes under its own lease, and nothing further is sent. The
            # rest of a round's calls land here rather than on the desktop.
            return f"{name} did not run: the job was stopped.", False
        if name == "todo_write":
            return self._todos(job, arguments), False
        if name not in names:
            return (
                f"{name} is not available to {job.name}. Use one of the offered tools, or "
                "say in your report that it was needed.",
                True,
            )

        key = self._key(root, str(arguments.get("path") or ""))
        if name in WRITES and key is not None and key.exists() and str(key) not in job.read:
            # Read-before-edit, as Claude Code enforces it: a change to a file
            # the agent has not looked at is a change to what it imagines.
            shown = str(arguments.get("path"))
            return f"Read {shown} with file_read before changing it; it has not been read in this job.", True

        use = self.granted if (job.mode == "fix" and name in GRANTED) else self.dispatch
        outcome = use(name, arguments)
        if outcome.get("status") == "confirmation_required":
            outcome = self._await_approval(job, name, arguments, str(outcome.get("token") or ""))

        status = outcome.get("status")
        if status == "failed":
            return f"{name} failed: {outcome.get('error') or 'no reason given'}", True
        if status == "denied":
            return (
                f"The owner denied {name}. It did not run. Do not try it again; carry on "
                "without it or say in your report that it was needed.",
                False,
            )
        if status == "expired":
            return (
                f"Nobody answered the confirmation for {name} in time, so it expired and did "
                "not run. Carry on without it or report that it is waiting for the owner.",
                False,
            )
        if status == "stopped":
            return f"{name} did not run: the job was stopped while it waited for approval.", False
        if name == "file_read" and key is not None:
            job.read.add(str(key))
        result = outcome.get("result")
        text = external_text(result) or wrap_external(f"tool:{name}", result).text
        return text[:MAX_RESULT], False

    def _todos(self, job: Job, arguments: dict[str, Any]) -> str:
        todos = [one for one in arguments.get("todos") or [] if isinstance(one, dict)]
        doing = [str(one.get("content") or "") for one in todos if one.get("status") == "in_progress"]
        job.progress = doing[0][:160] if doing else ""
        job.todos = [
            {"content": str(one.get("content") or "")[:160], "status": str(one.get("status") or "pending")}
            for one in todos[:20]
        ]
        done = sum(1 for one in todos if one.get("status") == "completed")
        return f"List saved: {done} of {len(todos)} done." + (f" Now: {job.progress}" if job.progress else "")

    # -- confirmation ------------------------------------------------------

    def _await_approval(
        self, job: Job, name: str, arguments: dict[str, Any], token: str
    ) -> dict[str, Any]:
        with self._lock:
            job.state = "awaiting_approval"
            job.token = token
            job.action = f"{name} {json.dumps(arguments, default=str)[:200]}"
            job.answered.clear()
            job.outcome = {}
            self._waiting[token] = job
        self._note(job, "approval", f"waiting for the owner: {_step(name, arguments)}")
        log.info("sub-agent waiting for approval", extra={"marvi_job": job.id, "marvi_tool": name})
        gone_since: float | None = None
        outcome: dict[str, Any] = {}
        while not job.answered.wait(0.05):
            if job.stop.is_set():
                outcome = {"status": "stopped"}
                break
            with self._lock:
                settling = token in self._settling
            if settling or self.pending(token):
                gone_since = None
                continue
            gone_since = gone_since or time.monotonic()
            if time.monotonic() - gone_since >= APPROVAL_GRACE:
                outcome = {"status": "expired"}
                break
        with self._lock:
            outcome = outcome or dict(job.outcome)
            self._waiting.pop(token, None)
            self._settling.discard(token)
            if job.state == "awaiting_approval":
                job.state = "running"
            job.token = job.action = ""
            job.active = time.monotonic()
        self._publish()
        return outcome

    def settling(self, token: str) -> None:
        """An approval path has taken this token and is running its action."""
        with self._lock:
            if token in self._waiting:
                self._settling.add(token)

    def settled(self, token: str, outcome: dict[str, Any]) -> None:
        """What happened to a token a sub-agent was waiting on. Any surface calls this."""
        with self._lock:
            job = self._waiting.get(token)
            if job is None:
                return
            job.outcome = dict(outcome)
        job.answered.set()

    def waiting_on(self, token: str) -> bool:
        with self._lock:
            return token in self._waiting

    def approve(self, job_id: str, approve: bool) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if job is None:
            return {"ok": False, "detail": f"no job {job_id!r}"}
        if job.state != "awaiting_approval" or not job.token:
            return {"ok": False, "detail": f"{job.name} is not waiting for anything"}
        if self.settle is None:
            return {"ok": False, "detail": "approvals are not connected in this Gateway"}
        answer = self.settle(job.token, bool(approve))
        return {"ok": answer.get("status") != "expired", "job": job.id, **answer}

    # -- following ---------------------------------------------------------

    def status(self, job_id: str = "") -> dict[str, Any]:
        with self._lock:
            if not job_id:
                return {"ok": True, "jobs": [job.as_dict() for job in self._jobs.values()]}
            job = self._jobs.get(job_id)
        if job is None:
            return {"ok": False, "detail": f"no job {job_id!r}"}
        return job.as_dict()

    def has(self, job_id: str) -> bool:
        return job_id in self._jobs

    def acting(self, agent: str) -> str:
        """The name of the live job this agent is running, or empty. For the Island."""
        with self._lock:
            return next((job.name for job in self._jobs.values() if job.agent == agent and job.live), "")

    def stop(self, job_id: str) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if job is None:
            return {"ok": False, "detail": f"no job {job_id!r}"}
        if not job.live:
            return {"ok": True, "detail": f"{job.name} had already {job.state}", **job.as_dict()}
        job.stop.set()
        self._end(job, "interrupted", "stopped", "the owner stopped it")
        return {"ok": True, "detail": f"stopped {job.name}, job {job.id}"}

    def steer(self, job_id: str, message: str) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        message = (message or "").strip()
        if job is None:
            return {"ok": False, "detail": f"no job {job_id!r}"}
        if not message:
            return {"ok": False, "detail": "nothing to tell it"}
        if not job.live:
            return {"ok": False, "detail": f"{job.name} has already {job.state}"}
        with self._lock:
            job.steering.append(message[:2000])
        # Queued, not delivered: it reaches the job at its next round.
        return {"ok": True, "detail": f"{job.name} will see that at its next step"}

    # -- the desktop's view ------------------------------------------------

    def _note(self, job: Job, kind: str, text: str, **extra: str) -> dict[str, Any]:
        event: dict[str, Any] = {"at": time.time(), "kind": kind, "text": text, **extra}
        with self._lock:
            job.events.append(event)
        self._publish()
        return event

    def _publish(self) -> None:
        with self._changed:
            self._revision += 1
            self._changed.notify_all()

    def overview(self) -> dict[str, Any]:
        """The roster and the recent jobs, without transcripts."""
        roster = [
            {
                "key": one.key,
                "name": "Worker" if one.names else one.key.title(),
                "description": one.description,
                "when_to_use": one.when_to_use,
                # A worker takes a new name each run, so the desktop seeds its
                # avatar per job rather than per agent.
                "named_per_job": bool(one.names),
            }
            for one in self.agents()
        ] + [
            # Outside coders Marvi can hand to over ACP, when they are installed.
            {
                "key": coder.key,
                "name": coder.name,
                "description": coder.description,
                "when_to_use": f"When {coder.name} is asked for by name.",
                "named_per_job": False,
            }
            for coder in acp_coders.installed()
        ]
        with self._lock:
            recent = sorted(self._jobs.values(), key=lambda job: -job.started_at)[:MAX_LISTED]
            jobs = [job.as_dict() for job in recent]
        return {"revision": self._revision, "agents": roster, "jobs": jobs}

    def watch(self, after: int | None = None, timeout: float = WATCH_TIMEOUT) -> dict[str, Any]:
        """The overview, once it differs from revision `after` or the wait ends."""
        if after is not None:
            with self._changed:
                self._changed.wait_for(lambda: self._revision != after, timeout)
        return self.overview()

    def job(self, job_id: str) -> dict[str, Any] | None:
        """One job with its whole task, transcript and list."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {
                **job.as_dict(),
                "task": job.task,
                "events": [dict(event) for event in job.events],
                "todos": [dict(one) for one in job.todos],
                "revision": self._revision,
            }

    def wait(self, job_id: str, timeout: float) -> Job:
        job = self._jobs[job_id]
        if job.thread is not None:
            job.thread.join(timeout)
        return job

    def _end(self, job: Job, state: str, reason: str, summary: str) -> None:
        with self._lock:
            if job.finished_at:
                return
            job.state, job.exit_reason, job.summary = state, reason, summary
            job.finished_at = time.time()
            job.progress = ""
        self._note(job, "end", summary[:300], state=state, reason=reason)
        log.info(
            "sub-agent finished",
            extra={"marvi_job": job.id, "marvi_state": state, "marvi_reason": reason},
        )

    def _watch(self) -> None:
        """Start the stall watcher if it is not running. Called under the lock."""
        if self._watching:
            return
        self._watching = True
        threading.Thread(target=self._watcher, daemon=True, name="marvi-subagent-watch").start()

    def _watcher(self) -> None:
        while True:
            time.sleep(WATCH_EVERY)
            with self._lock:
                live = [job for job in self._jobs.values() if job.live]
                if not live:
                    self._watching = False
                    return
            now = time.monotonic()
            for job in live:
                # Waiting on the owner is not being stuck.
                patience = STALL_IN_TOOL if job.in_tool else STALL_SECONDS
                if job.state == "running" and now - job.active > patience:
                    job.stop.set()
                    self._end(
                        job, "failed", "stalled",
                        f"it made no progress for {round(patience)} seconds, so it was stopped",
                    )


def register_subagent_tools(registry: Any, runner: Runner) -> None:
    from . import delegate as outside
    from .tools import ToolSpec

    roster = "; ".join(f"{one.key} -- {one.when_to_use}" for one in runner.agents())

    def delegated_status(job: str = "") -> dict[str, Any]:
        # Outside coders keep their own registry until ACP replaces it.
        if job and not runner.has(job):
            return outside.status(job)
        answer = runner.status(job)
        if not job:
            answer["jobs"] = answer["jobs"] + outside.status().get("jobs", [])
        return answer

    registry.register(
        ToolSpec(
            name="delegate",
            description=(
                "Hand a multi-step job to one of your sub-agents and get a job id back at once. "
                "It works in the background; keep talking, and its report reaches you when it "
                "finishes. Harvi codes, Jarvi drives desktop apps, Talos drives the browser, "
                "worker takes any other long job."
            ),
            arguments={"agent": str, "task": str},
            optional={"mode": str},
            describes={
                "agent": f"Which sub-agent: {roster}",
                "task": (
                    "Everything it needs, written for someone who cannot see this conversation: "
                    "the goal, where to look, and what you already know or ruled out."
                ),
                "mode": (
                    "Harvi only. investigate (default) reads and reports without changing "
                    "anything; fix lets it edit and run commands, and needs the owner's say-so."
                ),
            },
            sensitive=False,
            # Letting Harvi change code is the owner's decision; every other
            # sensitive action inside a job is confirmed on its own.
            sensitive_when=lambda args: str(args.get("mode") or "").lower() == "fix",
            handler=lambda agent, task, mode="": runner.start(agent, task, mode),
        )
    )
    registry.register(
        ToolSpec(
            name="delegated_status",
            description=(
                "Check handed-off work by job id: whether it is still running, waiting for "
                "approval, or finished, and its report if it has one. Omit the id for every job."
            ),
            arguments={},
            optional={"job": str},
            describes={"job": "The job id. Omit for every job."},
            sensitive=False,
            handler=delegated_status,
        )
    )
    registry.register(
        ToolSpec(
            name="delegate_stop",
            description=(
                "Stop a sub-agent's job by id when the owner changes their mind. Work it already "
                "did stays done; for Jarvi, issued desktop actions are drained first."
            ),
            arguments={"job": str},
            sensitive=False,
            handler=lambda job: runner.stop(job),
        )
    )
    registry.register(
        ToolSpec(
            name="delegate_steer",
            description=(
                "Tell a running sub-agent something new -- a correction or a narrower goal -- "
                "without stopping it. It reads the message at its next step."
            ),
            arguments={"job": str, "message": str},
            sensitive=False,
            handler=lambda job, message: runner.steer(job, message),
        )
    )
    def delegate_to_coder(task: str, coder: str = "claude", mode: str = "investigate") -> dict[str, Any]:
        # Over ACP when the coder has an ACP server here; the old one-shot CLI
        # otherwise, so a machine without the adapter still has its coder.
        chosen = acp_coders.CODERS.get((coder or "").strip().lower())
        if chosen is not None and chosen.command():
            return runner.start(chosen.key, task, mode)
        return outside.start(task, coder, mode)

    registry.register(
        ToolSpec(
            name="delegate_to_coder",
            description=(
                "Hand a coding job to an outside coding agent -- Claude Code, Codex, OpenCode or "
                "Gemini CLI -- when the owner asks for one by name, and get a job id back at once."
            ),
            arguments={"task": str},
            optional={"coder": str, "mode": str},
            describes={
                "task": (
                    "What to do, written for someone who cannot see this conversation: "
                    "the symptom, where it shows, and what you already ruled out."
                ),
                "coder": "claude, codex, opencode or gemini. Default claude.",
                "mode": (
                    "investigate to look and report without changing anything (default), "
                    "or fix to let it edit files and run commands."
                ),
            },
            # It runs an agent against the user's source code. Theirs to allow.
            sensitive=True,
            handler=delegate_to_coder,
        )
    )
    registry.register(
        ToolSpec(
            name="coder_permission",
            description="Let an outside coding agent take one step that needs the owner's approval",
            arguments={"job": str, "coder": str, "kind": str, "action": str},
            sensitive=True,
            # Carries an ACP permission request through the one confirmation
            # path; approving it is the whole effect. No model is offered it.
            internal=True,
            handler=lambda job, coder, kind, action: {"approved": True, "job": job},
        )
    )
    registry.register(
        ToolSpec(
            name="delegate_approve",
            description=(
                "Answer a sub-agent that is waiting for the owner's approval. Only after the "
                "owner has actually said yes or no to the exact action it asked about."
            ),
            arguments={"job": str, "approve": bool},
            describes={"approve": "True when the owner said yes, false when they said no."},
            sensitive=False,
            handler=lambda job, approve: runner.approve(job, approve),
        )
    )
