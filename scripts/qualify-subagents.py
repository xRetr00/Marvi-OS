"""Real Gateway -> real provider -> Harvi / Jarvi qualification.

Builds the full Gateway, points the workspace at a disposable repository with
one failing test, and hands Harvi a fix job over `POST /tools/delegate` -- the
path voice takes -- including the one confirmation a fix job asks for. The fix
is verified independently by running the fixture's tests here, not by trusting
the report. With `--jarvi`, Jarvi also opens and closes Notepad through the
real Cua worker.

Prints one JSON line of evidence per job: how long `delegate` took to answer
(what the voice turn pays), how long the job ran, its state and its report.

    .venv/Scripts/python.exe scripts/qualify-subagents.py [--jarvi]
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

fixture = Path(tempfile.mkdtemp(prefix="marvi-harvi-proof-"))
(fixture / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
(fixture / "test_calc.py").write_text(
    "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8"
)
os.environ["MARVI_WORKSPACE_ROOT"] = str(fixture)

from fastapi.testclient import TestClient
from marvi_gateway.app import create_app

app = create_app(version="qualify-subagents")
runner = app.state.subagents
client = TestClient(app)


def delegate(arguments: dict, tool: str = "delegate") -> tuple[dict, float]:
    """`POST /tools/<tool>`, settling a confirmation the way the Island does."""
    started = time.perf_counter()
    answer = client.post(f"/tools/{tool}", json={"arguments": arguments}).json()
    if answer.get("status") == "confirmation_required":
        answer = client.post(
            f"/confirmations/{answer['token']}",
            json={"decision": "approve", "arguments": arguments},
        ).json()
    return answer, round((time.perf_counter() - started) * 1000, 1)


def run(arguments: dict, timeout: float = 600, tool: str = "delegate") -> dict:
    arguments = {key: value for key, value in arguments.items() if not (tool != "delegate" and key == "agent")}
    answer, answered_ms = delegate(arguments, tool)
    assert answer.get("status") == "executed" and answer["result"]["ok"], answer
    job_id = answer["result"]["id"]
    deadline = time.monotonic() + timeout
    while (state := runner.status(job_id)["state"]) in ("running", "awaiting_approval"):
        if state == "awaiting_approval":
            # Unattended: approve through the same path `delegate_approve`
            # takes, and record exactly what was approved.
            print(json.dumps({"approved": runner.status(job_id)["action"]}), flush=True)
            runner.approve(job_id, True)
        if time.monotonic() > deadline:
            runner.stop(job_id)
            break
        time.sleep(1)
    job = runner.status(job_id)
    return {
        "agent": job["agent"],
        "job": job_id,
        "delegate_answered_ms": answered_ms,
        "job_seconds": job["seconds"],
        "state": job["state"],
        "exit_reason": job["exit_reason"],
        "tokens": job["tokens"],
        "summary": job["summary"][:600],
    }


harvi = None if "--acp" in sys.argv else run(
    {
        "agent": "harvi",
        "mode": "fix",
        "task": (
            "test_calc.py fails: add(2, 3) should be 5. Find why, fix calc.py, and run the "
            "tests with `python -m pytest -q` to prove it."
        ),
    }
)
if harvi is not None:
    verified = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(fixture)],
        cwd=fixture,
        capture_output=True,
        text=True,
        check=False,
    )
    tail = verified.stdout.strip().splitlines()
    harvi["independent_pytest"] = tail[-1] if tail else verified.stderr[-200:]
    harvi["calc_py"] = (fixture / "calc.py").read_text(encoding="utf-8")
    print(json.dumps(harvi), flush=True)

if "--acp" in sys.argv:
    # Each installed outside coder, over ACP, on the same failing fixture.
    from marvi_gateway import acp_coders

    for coder in acp_coders.installed():
        (fixture / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        row = run(
            {
                "agent": "delegate_to_coder",
                "coder": coder.key,
                "mode": "fix",
                "task": (
                    "test_calc.py fails: add(2, 3) should be 5. Fix calc.py and run "
                    "`python -m pytest -q` to prove it."
                ),
            },
            tool="delegate_to_coder",
        )
        checked = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(fixture)],
            cwd=fixture,
            capture_output=True,
            text=True,
            check=False,
        )
        tail = checked.stdout.strip().splitlines()
        row["coder"] = coder.key
        row["independent_pytest"] = tail[-1] if tail else checked.stderr[-200:]
        row["calc_py"] = (fixture / "calc.py").read_text(encoding="utf-8")
        row["transcript"] = [
            f"{e['kind']}:{e.get('outcome', '')}:{e['text'][:80]}"
            for e in (runner.job(row["job"]) or {}).get("events", [])
        ]
        print(json.dumps(row), flush=True)

if "--jarvi" in sys.argv:
    jarvi = run(
        {
            "agent": "jarvi",
            "task": "Open Notepad, tell me the title of its window, then close Notepad. Nothing needs saving.",
        },
        timeout=300,
    )
    listed = subprocess.run(
        ["tasklist", "/fi", "imagename eq notepad.exe"],
        capture_output=True,
        text=True,
        check=False,
    )
    jarvi["notepad_still_running"] = "notepad.exe" in listed.stdout.lower()
    print(json.dumps(jarvi), flush=True)
