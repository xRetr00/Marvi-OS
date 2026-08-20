"""Measuring what a turn costs, before changing how a turn is made.

Phase 12 routes every LLM call through the Gateway, which puts a loopback HTTP
hop on the voice path. Voice is the one surface where that could be a mistake,
so the plan says measure first and stop if it regresses — and a plan that says
"measure" without a way to measure is a plan that skips the measurement.

What matters here is **first token**, not total time. A voice turn starts
speaking as soon as tokens arrive; total response time is nearly irrelevant to
how fast Marvi feels. A change that improves total time and worsens first token
has made voice worse.

Recorded as a JSONL file rather than a metrics system: this exists to answer
one question a handful of times, and a file that can be read with `cat` and
deleted afterwards is the right size for that.
"""

from __future__ import annotations

import json
import statistics
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import paths
from .logs import get_logger

log = get_logger("providers")

#: Above this, the extra hop is not worth it and Phase 12 needs a different
#: seam — an in-process adapter, or the agent importing ProviderClient rather
#: than crossing a socket. Stated in the roadmap; enforced by `compare`.
FIRST_TOKEN_BUDGET_MS = 150.0


@dataclass
class Sample:
    """One LLM call, timed."""

    surface: str
    path: str
    #: Empty when the caller does not know yet — a failure before resolution
    #: is still a sample worth keeping.
    provider: str = ""
    model: str = ""
    #: Time from request to the first token. The number that matters.
    first_token_ms: float | None = None
    total_ms: float | None = None
    tokens: int = 0
    error: str = ""
    at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def recording_path() -> Path:
    return paths.root() / "latency.jsonl"


def record(sample: Sample) -> None:
    """Append one sample. Never raises: measurement must not break a turn."""
    try:
        path = recording_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(sample.as_dict()) + "\n")
    except OSError as exc:
        log.warning("could not record a latency sample: %s", exc)


@contextmanager
def timed(surface: str, path: str, provider: str = "", model: str = "") -> Iterator[Sample]:
    """Time a call, recording whatever happened.

    The caller marks first token itself, because only the caller knows when one
    arrived:

        with timed("voice", "direct", provider, model) as sample:
            for chunk in stream:
                sample.mark_first_token()   # a no-op after the first
                ...
    """
    sample = Sample(surface=surface, path=path, provider=provider, model=model)
    started = time.perf_counter()

    def mark_first_token() -> None:
        if sample.first_token_ms is None:
            sample.first_token_ms = (time.perf_counter() - started) * 1000

    sample.mark_first_token = mark_first_token  # type: ignore[attr-defined]
    try:
        yield sample
    except Exception as exc:
        sample.error = f"{type(exc).__name__}: {exc}"[:200]
        raise
    finally:
        sample.total_ms = (time.perf_counter() - started) * 1000
        record(sample)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
    return ordered[index]


def summarise(surface: str | None = None, path: str | None = None) -> dict[str, Any]:
    """Median and p95 first-token time, per surface and path.

    Median and p95 rather than a mean: one slow cold start would drag a mean
    and tell you nothing about the turn you are about to take.
    """
    file = recording_path()
    if not file.is_file():
        return {"samples": 0, "detail": "nothing recorded yet"}

    groups: dict[tuple[str, str], tuple[list[float], list[float]]] = {}
    errors = 0
    for line in file.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if surface and row.get("surface") != surface:
            continue
        if path and row.get("path") != path:
            continue
        if row.get("error"):
            errors += 1
            continue
        key = (row.get("surface", "?"), row.get("path", "?"))
        first, total = row.get("first_token_ms"), row.get("total_ms")
        # A row with no first token is still a row. Skipping them entirely
        # meant chat -- which does not stream, so genuinely has none -- was
        # written to the recording and then reported as nothing recorded.
        firsts, totals = groups.setdefault(key, ([], []))
        if first is not None:
            firsts.append(float(first))
        if total is not None:
            totals.append(float(total))

    return {
        "samples": sum(max(len(firsts), len(totals)) for firsts, totals in groups.values()),
        "errors": errors,
        "groups": [
            {
                "surface": key[0],
                "path": key[1],
                "count": max(len(firsts), len(totals)),
                # Absent rather than zero where a surface does not stream.
                # A zero here would read as instant rather than not measured.
                "first_token_median_ms": (
                    round(statistics.median(firsts), 1) if firsts else None
                ),
                "first_token_p95_ms": (
                    round(_percentile(firsts, 0.95), 1) if firsts else None
                ),
                "total_median_ms": round(statistics.median(totals), 1) if totals else None,
                "total_p95_ms": round(_percentile(totals, 0.95), 1) if totals else None,
            }
            for key, (firsts, totals) in sorted(groups.items())
        ],
    }


def compare(surface: str, before: str, after: str) -> dict[str, Any]:
    """Did routing through the Gateway cost more than the budget allows?

    The gate for Phase 12. `before` and `after` are path labels — `direct` and
    `gateway` — recorded by the same surface.
    """
    report = summarise(surface=surface)
    by_path = {group["path"]: group for group in report.get("groups", [])}
    old, new = by_path.get(before), by_path.get(after)
    if not old or not new:
        missing = before if not old else after
        return {"ready": False, "detail": f"no samples recorded for {surface}/{missing}"}

    delta = new["first_token_median_ms"] - old["first_token_median_ms"]
    return {
        "ready": True,
        "before_ms": old["first_token_median_ms"],
        "after_ms": new["first_token_median_ms"],
        "delta_ms": round(delta, 1),
        "budget_ms": FIRST_TOKEN_BUDGET_MS,
        "within_budget": delta <= FIRST_TOKEN_BUDGET_MS,
        "detail": (
            f"first token {old['first_token_median_ms']}ms to "
            f"{new['first_token_median_ms']}ms ({delta:+.1f}ms)"
        ),
    }
