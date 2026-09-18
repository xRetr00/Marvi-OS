"""One turn, as the list of things it did -- and doing it again, safely.

Marvi could always answer "what did that cost" in totals and "what happened" in
four log files. What she could not answer is the question anybody actually has
after a strange reply: *what did this particular turn do, in order, and what
would it do differently now?*

A run is that list. Every model call and every tool call in a turn carries the
same trace id, they are appended to the observation journal as they happen, and
`journal()` reads one back in order.

## Replay is a dry run, and that is the whole design

"Replay" that can send an email is not a debugging tool, it is a second email.
So a replay never executes a tool: each tool step is answered with the result
that was *recorded*, and the model is free to take a different path -- which is
the interesting part, because a different path is exactly what a changed prompt
or a changed model produces. What comes back is a comparison, not a re-run:

    asked        the turn's own user message
    was          the tools it called, and the answer it gave
    now          the tools this model calls, and the answer it gives

Nothing in a replay reaches the world: no tool runs, nothing is stored in the
conversation, and the memory pass does not run. The only cost is the model call.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from . import observations
from .logs import get_logger

log = get_logger("gateway")

#: How many steps one replayed turn may take before it is called a loop.
MAX_ROUNDS = 6


def new_trace() -> str:
    """The id every step of one turn carries."""
    return uuid4().hex[:12]


def step(trace: str, kind: str, **fields: Any) -> None:
    """Record one thing a turn did. Never raises; see `observations.record`."""
    if not trace:
        return
    observations.record("run", trace=trace, event=kind, **fields)


def journal(trace: str, limit: int = 400) -> list[dict[str, Any]]:
    """Everything one turn did, oldest first."""
    rows = [row for row in observations.read("run", limit=limit * 4) if row.get("trace") == trace]
    return sorted(rows, key=lambda row: float(row.get("at") or 0.0))[:limit]


def traces(limit: int = 20) -> list[dict[str, Any]]:
    """The most recent turns, newest first, with what each one did."""
    seen: dict[str, dict[str, Any]] = {}
    for row in observations.read("run", limit=limit * 40):
        trace = str(row.get("trace") or "")
        if not trace:
            continue
        held = seen.setdefault(
            trace,
            {"trace": trace, "at": row.get("at"), "surface": row.get("surface", ""), "steps": 0,
             "tools": [], "asked": "", "tokens": 0},
        )
        held["steps"] += 1
        held["at"] = max(float(held["at"] or 0), float(row.get("at") or 0))
        if row.get("event") == "asked":
            held["asked"] = str(row.get("text") or "")
            held["surface"] = str(row.get("surface") or held["surface"])
        if row.get("event") == "tool":
            held["tools"].append(str(row.get("name") or ""))
        if row.get("event") == "answered":
            held["tokens"] = int(row.get("tokens") or 0)
    return sorted(seen.values(), key=lambda held: float(held["at"] or 0), reverse=True)[:limit]


def recorded_results(rows: list[dict[str, Any]]) -> dict[str, str]:
    """What each tool answered the first time, by name and arguments."""
    answers: dict[str, str] = {}
    for row in rows:
        if row.get("event") == "tool":
            answers[f"{row.get('name')}:{row.get('args', '')}"] = str(row.get("result") or "")
    return answers


def replay(client: Any, trace: str, model: str = "", provider: str = "") -> dict[str, Any]:
    """Run one recorded turn again against a model, executing nothing.

    The tools are *answered*, not called: a step the model takes that the
    original also took gets the recorded result, and a step it invents gets a
    plain note saying so. Either way nothing happens to the world.
    """
    rows = journal(trace)
    if not rows:
        return {"error": f"no run called {trace}"}
    asked = next((str(row.get("text") or "") for row in rows if row.get("event") == "asked"), "")
    if not asked:
        return {"error": "that run did not record what was asked"}

    was_tools = [str(row.get("name") or "") for row in rows if row.get("event") == "tool"]
    was_answer = next(
        (str(row.get("text") or "") for row in rows if row.get("event") == "answered"), ""
    )
    answers = recorded_results(rows)

    messages = [
        {
            "role": "system",
            "content": (
                "You are replaying a recorded conversation turn for comparison. "
                "Tools are answered from a recording and nothing you ask for is "
                "actually carried out."
            ),
        },
        {"role": "user", "content": asked},
    ]
    started = time.perf_counter()
    now_tools: list[str] = []
    answer = ""
    for _round in range(MAX_ROUNDS):
        completion = client.call_with_fallback(
            messages, job="aux", model=model or None, provider=provider or None
        )
        calls = list(getattr(completion, "tool_calls", []) or [])
        answer = (getattr(completion, "text", "") or "").strip()
        if not calls:
            break
        for call in calls:
            name = str(call.get("name") or "")
            now_tools.append(name)
            key = f"{name}:{call.get('arguments', '')}"
            recorded = answers.get(key) or answers.get(f"{name}:")
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"[replay] {name} answered: {recorded}"
                        if recorded is not None
                        else f"[replay] {name} was not called in the recorded run, so there is "
                        "nothing to answer it with. Continue without it."
                    ),
                }
            )
    return {
        "trace": trace,
        "asked": asked,
        "was": {"tools": was_tools, "answer": was_answer},
        "now": {"tools": now_tools, "answer": answer, "model": model or "the configured model"},
        "same_tools": was_tools == now_tools,
        "ms": round((time.perf_counter() - started) * 1000),
        # Said out loud in the result, because the whole safety of this rests
        # on it and a reader should not have to take it on trust.
        "executed": "nothing; tools were answered from the recording",
    }
