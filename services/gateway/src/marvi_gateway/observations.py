"""What Marvi actually did, kept so it can be scored later.

Every finding in `docs/evals/` was made the same way: read a log, notice
something wrong, write a case for it. That works and it does not scale --
the interesting events are spread across four log files in four formats, most
of what matters is not logged at all, and finding a p90 meant a regex over
`agent.log`.

This is the same idea as `latency.jsonl`, widened. One append-only file, one
row per thing that happened, in a shape the eval harnesses can read directly.
The point is not observability. It is that **the next eval case should come
from what Marvi did last week, not from somebody remembering to look.**

## What is recorded, and why each one

`recall`    A question, how well the search scored, whether a reader answered
            or abstained. The store's own confidence numbers were computed and
            thrown away for months; the one time they were looked at they
            separated "found something" from "returned five things anyway"
            immediately.

`store`     What the memory worker decided about a turn. It ran for weeks
            keeping 17 of every 25 facts it should have, and nothing said so:
            an extraction that returns `[]` looks exactly like a turn with
            nothing in it.

`gate`      What a connector offered and what was kept. A regex here silently
            dropped an exam result, a dentist appointment and a rent bill.

`tool`      Which tool was called, whether it worked, how long it took, and --
            the row that matters most -- when the model searched for a tool and
            found nothing. That is the only honest signal about which tools
            Marvi is missing, and it currently reaches nobody.

`reply`     What was spoken, with the pipeline timings and the size of what
            went in. Prompt leaks, monologues and confabulations are all
            visible here and were all found by hand.

## Privacy

Local, in Marvi's own state directory, never sent anywhere -- the same
contract as the memory store it describes. It holds questions and short
excerpts because an eval cannot score what it cannot see; it does not hold
whole memories, whole replies or credentials. `MAX_TEXT` is the cap and
`redact` is applied to everything before it is written.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from .logs import get_logger

log = get_logger("memory")

SETTING = "MARVI_OBSERVATIONS"

#: Rows worth keeping. Older ones are dropped from the front, because this is
#: evidence for the next eval rather than an archive: a week of real use is
#: more than any suite here reads, and an unbounded file on a machine that
#: runs continuously is a disk that fills.
MAX_ROWS = 20_000

#: How much of any single piece of text is kept. Long enough to recognise a
#: prompt leak or a monologue, short enough that this is not a second copy of
#: the conversation.
MAX_TEXT = 400

_lock = threading.Lock()


def enabled() -> bool:
    return os.environ.get(SETTING, "on").strip().lower() not in ("0", "false", "no", "off")


def path() -> Path:
    from .paths import root

    return root() / "state" / "observations.jsonl"


def _clip(value: Any) -> Any:
    """Text shortened and redacted; anything else passed through."""
    if not isinstance(value, str):
        return value
    from .logs import redactor

    try:
        cleaned = redactor().scrub(value)
    except Exception:  # pragma: no cover - depends on the redactor
        cleaned = value
    return cleaned[:MAX_TEXT]


def record(kind: str, **fields: Any) -> None:
    """Append one observation. Never raises, never blocks anything real.

    Called from the paths it describes -- a recall, a store decision, a tool
    call -- so it has to cost nothing worth measuring and fail silently. An
    observation that broke a turn would be worse than no observation.
    """
    if not enabled():
        return
    row = {"at": round(time.time(), 3), "kind": kind}
    row.update({name: _clip(value) for name, value in fields.items()})
    try:
        target = path()
        with _lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:  # pragma: no cover - depends on the filesystem
        log.debug("could not record an observation: %s", exc)


def read(kind: str | None = None, limit: int = 1_000) -> list[dict[str, Any]]:
    """The most recent observations, newest last. Never raises."""
    try:
        lines = path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in reversed(lines):
        if len(rows) >= limit:
            break
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if kind is None or row.get("kind") == kind:
            rows.append(row)
    return list(reversed(rows))


def prune() -> int:
    """Drop the oldest rows past `MAX_ROWS`. Returns how many went."""
    try:
        target = path()
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    if len(lines) <= MAX_ROWS:
        return 0
    keep = lines[-MAX_ROWS:]
    try:
        with _lock:
            target.write_text("\n".join(keep) + "\n", encoding="utf-8")
    except OSError:  # pragma: no cover - depends on the filesystem
        return 0
    return len(lines) - len(keep)


def summarise() -> dict[str, Any]:
    """What has accumulated, for the page and for deciding whether to run a suite.

    Counts rather than content: the question this answers is "is there enough
    real use here to learn something", and the suites read the rows themselves.
    """
    rows = read(limit=MAX_ROWS)
    kinds: dict[str, int] = {}
    for row in rows:
        kinds[str(row.get("kind"))] = kinds.get(str(row.get("kind")), 0) + 1
    oldest = rows[0]["at"] if rows else None
    return {
        "rows": len(rows),
        "kinds": kinds,
        "since": oldest,
        "days": round((time.time() - oldest) / 86_400, 1) if oldest else 0.0,
        "enabled": enabled(),
        "path": str(path()),
    }
