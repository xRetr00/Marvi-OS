"""Handing a coding job to a coding agent.

Marvi finds her own bugs -- she reads her own logs now -- and she is not the
thing that should fix them. Claude Code and Codex are already installed on this
machine, they are built for exactly this, and they leave their work in git
where it can be read before it is kept.

## Two modes, and the default is the safe one

`investigate` runs the agent read-only: it looks and reports, and cannot change
a file. `fix` lets it edit. The distinction is passed to the underlying CLI as
its own sandbox setting rather than being enforced here, because those tools
police their own file access far better than a wrapper around them could.

Investigate is the default because "find out why the room will not connect" is
the common request, and "change my source code" is not something anybody should
arrive at by omission.

## It runs where Marvi is already allowed to work

`MARVI_WORKSPACE_ROOT`, the same allowlisted root the file tools use. Absent
configuration means this refuses rather than defaulting to the whole disk: a
coding agent pointed at an unconfigured root is the worst possible place to
start guessing.

## Started, not awaited

A coding agent takes minutes. Nothing here blocks on one: starting returns an
id, the work continues on a thread, and the result is collected later. That is
what lets a spoken conversation carry on while the job runs.

Jobs live in memory. One lost to a restart is not lost work -- the agent's
changes are on disk and in git, which is the durable record.

## The task goes on stdin, never in the argument list

On Windows these tools are `.CMD` shims -- `codex` resolves to `codex.CMD` --
and Windows runs a `.CMD` through `cmd.exe`, which re-parses the arguments it
was given. A task is text a language model wrote from something a person said,
so an `&` or a `|` in it would be read by the shell rather than by the coding
agent. Both CLIs read their prompt from stdin, so it is never an argument and
there is nothing for a shell to re-parse.

The resolved path from `shutil.which` is used as argv[0] for the same class of
reason: passing the bare name let Windows fail to find `codex.CMD` at all,
because `CreateProcess` does not apply PATHEXT the way a shell does.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .logs import get_logger
from .workspace import default_root

log = get_logger("delegate")

#: Long enough for real work, short enough that a wedged agent is not forever.
TIMEOUT = 1800
MAX_OUTPUT = 8_000
MAX_TASK = 4_000
#: More than this at once is a queue, and a queue is a thing to build when
#: somebody actually wants one.
MAX_RUNNING = 3


@dataclass
class Coder:
    name: str
    command: str
    #: Arguments per mode. Read-only first; it is the default.
    investigate: tuple[str, ...]
    fix: tuple[str, ...]
    why: str


CODERS = {
    "claude": Coder(
        name="claude",
        command="claude",
        investigate=("-p", "--permission-mode", "plan"),
        fix=("-p", "--permission-mode", "acceptEdits"),
        why="Claude Code. Strong on reading an unfamiliar codebase and explaining it.",
    ),
    "codex": Coder(
        name="codex",
        command="codex",
        investigate=("exec", "--sandbox", "read-only"),
        fix=("exec", "--sandbox", "workspace-write"),
        why="Codex. Strong on making a contained change and running the tests.",
    ),
}


@dataclass
class Job:
    id: str
    coder: str
    mode: str
    task: str
    root: str
    state: str = "running"
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    output: str = ""
    exit_code: int | None = None

    @property
    def seconds(self) -> float:
        return (self.finished_at or time.time()) - self.started_at

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "coder": self.coder,
            "mode": self.mode,
            "task": self.task[:200],
            "state": self.state,
            "seconds": round(self.seconds, 1),
            "output": self.output[-MAX_OUTPUT:],
            "exit_code": self.exit_code,
        }


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def available() -> list[dict[str, str]]:
    """Which coding agents are actually on this machine."""
    return [
        {"name": coder.name, "why": coder.why}
        for coder in CODERS.values()
        if shutil.which(coder.command)
    ]


def _run(job: Job, argv: list[str]) -> None:
    try:
        # The task arrives on stdin. Nothing model-written is in `argv`, which
        # is what keeps a `.CMD` shim's shell out of the picture entirely.
        finished = subprocess.run(
            argv,
            input=job.task,
            cwd=job.root,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
        job.output = (finished.stdout or "") + (
            f"\n[stderr]\n{finished.stderr}" if (finished.stderr or "").strip() else ""
        )
        job.exit_code = finished.returncode
        job.state = "done" if finished.returncode == 0 else "failed"
    except subprocess.TimeoutExpired:
        job.state = "timed out"
        job.output = f"no answer after {TIMEOUT // 60} minutes"
    except (OSError, ValueError) as exc:
        job.state = "failed"
        job.output = str(exc)
    finally:
        job.finished_at = time.time()
        log.info(
            "delegated job finished",
            extra={"marvi_job": job.id, "marvi_state": job.state, "marvi_coder": job.coder},
        )


def start(task: str, coder: str = "claude", mode: str = "investigate") -> dict[str, Any]:
    """Hand a job to a coding agent. Returns immediately with an id."""
    task = (task or "").strip()
    if not task:
        return {"ok": False, "detail": "nothing to delegate"}
    if len(task) > MAX_TASK:
        return {"ok": False, "detail": f"that task is longer than {MAX_TASK} characters"}
    if mode not in ("investigate", "fix"):
        return {"ok": False, "detail": "mode is investigate or fix"}

    chosen = CODERS.get(coder)
    if chosen is None:
        return {
            "ok": False,
            "detail": f"no coding agent called {coder!r}",
            "available": available(),
        }
    executable = shutil.which(chosen.command)
    if not executable:
        return {"ok": False, "detail": f"{coder} is not installed", "available": available()}

    root = default_root()
    if root is None:
        return {
            "ok": False,
            "detail": (
                "no workspace root is configured, so there is nowhere a coding agent is "
                "allowed to work. Set MARVI_WORKSPACE_ROOT."
            ),
        }

    with _lock:
        running = [job for job in _jobs.values() if job.state == "running"]
        if len(running) >= MAX_RUNNING:
            return {
                "ok": False,
                "detail": f"{len(running)} delegated jobs are already running",
                "running": [job.id for job in running],
            }
        job = Job(id=uuid.uuid4().hex[:8], coder=coder, mode=mode, task=task, root=str(root))
        _jobs[job.id] = job

    argv = [executable, *(chosen.fix if mode == "fix" else chosen.investigate)]
    threading.Thread(target=_run, args=(job, argv), daemon=True).start()
    log.info(
        "delegated a job",
        extra={"marvi_job": job.id, "marvi_coder": coder, "marvi_mode": mode},
    )
    verb = "fixing" if mode == "fix" else "looking into"
    return {
        "ok": True,
        "id": job.id,
        "state": "running",
        "detail": f"{coder} is {verb} it, job {job.id}",
    }


def status(job_id: str = "") -> dict[str, Any]:
    """One job, or all of them."""
    with _lock:
        if not job_id:
            return {"ok": True, "jobs": [job.as_dict() for job in _jobs.values()]}
        job = _jobs.get(job_id)
    if job is None:
        return {"ok": False, "detail": f"no job {job_id!r}"}
    return {"ok": True, **job.as_dict()}


def register_delegate_tools(registry: Any) -> None:
    from .tools import ToolSpec

    registry.register(
        ToolSpec(
            name="delegate_to_coder",
            description="Hand a coding job to a coding agent",
            arguments={"task": str},
            optional={"coder": str, "mode": str},
            describes={
                "task": (
                    "What to do, written for someone who cannot see this conversation: "
                    "the symptom, where it shows, and what you already ruled out."
                ),
                "coder": "claude or codex. Default claude.",
                "mode": (
                    "investigate to look and report without changing anything (default), "
                    "or fix to let it edit files."
                ),
            },
            # It runs an agent that can edit the user's source code. Theirs to allow.
            sensitive=True,
            handler=lambda task, coder="claude", mode="investigate": start(task, coder, mode),
        )
    )
    registry.register(
        ToolSpec(
            name="delegated_status",
            description="Check a delegated job",
            arguments={},
            optional={"job": str},
            describes={"job": "The job id. Omit for every job."},
            sensitive=False,
            handler=lambda job="": status(job),
        )
    )
