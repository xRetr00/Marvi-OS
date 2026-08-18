"""Latency measurement.

The gate for Phase 12 is a number, so the thing producing the number has to be
right about which number it is: first token, not total, and a median rather
than a mean.
"""

from __future__ import annotations

import json

import pytest

from marvi_gateway import latency


@pytest.fixture(autouse=True)
def recording(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    yield tmp_path


def test_a_call_records_first_token_separately_from_total() -> None:
    with latency.timed("voice", "direct", "openai", "gpt-5") as sample:
        sample.mark_first_token()

    rows = [json.loads(line) for line in latency.recording_path().read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["surface"] == "voice"
    assert rows[0]["first_token_ms"] is not None
    # Total is always at least first token; a turn cannot finish before it starts.
    assert rows[0]["total_ms"] >= rows[0]["first_token_ms"]


def test_only_the_first_token_is_the_first_token() -> None:
    with latency.timed("voice", "direct") as sample:
        sample.mark_first_token()
        first = sample.first_token_ms
        sample.mark_first_token()

    assert sample.first_token_ms == first


def test_a_failed_call_is_recorded_rather_than_lost() -> None:
    with pytest.raises(RuntimeError), latency.timed("chat", "gateway"):
        raise RuntimeError("provider refused")

    rows = [json.loads(line) for line in latency.recording_path().read_text().splitlines()]
    assert "provider refused" in rows[0]["error"]
    # A failure has no first token, and must not be counted as a fast one.
    assert rows[0]["first_token_ms"] is None


def test_failures_are_excluded_from_the_summary() -> None:
    for _ in range(3):
        with latency.timed("voice", "direct") as sample:
            sample.mark_first_token()
    with pytest.raises(RuntimeError), latency.timed("voice", "direct"):
        raise RuntimeError("nope")

    report = latency.summarise("voice")
    assert report["samples"] == 3
    assert report["errors"] == 1


def test_measurement_never_breaks_a_turn(monkeypatch) -> None:
    # A turn must not fail because the measurement of it could not be written.
    def refuse(*_args, **_kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(latency.Path, "open", refuse)
    with latency.timed("voice", "direct") as sample:
        sample.mark_first_token()


def test_the_comparison_is_the_phase_gate() -> None:
    """`compare` answers the one question: did the extra hop cost too much."""
    for value in (100.0, 100.0, 100.0):
        sample = latency.Sample("voice", "direct", "p", "m", first_token_ms=value)
        latency.record(sample)
    for value in (140.0, 140.0, 140.0):
        latency.record(latency.Sample("voice", "gateway", "p", "m", first_token_ms=value))

    verdict = latency.compare("voice", "direct", "gateway")

    assert verdict["ready"] is True
    assert verdict["delta_ms"] == 40.0
    assert verdict["within_budget"] is True


def test_a_regression_past_the_budget_fails_the_gate() -> None:
    latency.record(latency.Sample("voice", "direct", first_token_ms=100.0))
    latency.record(latency.Sample("voice", "gateway", first_token_ms=400.0))

    verdict = latency.compare("voice", "direct", "gateway")

    # 300ms on the voice path is the answer being "no", not a number to accept.
    assert verdict["within_budget"] is False
    assert verdict["delta_ms"] == 300.0


def test_the_gate_refuses_to_answer_without_both_sides() -> None:
    latency.record(latency.Sample("voice", "direct", first_token_ms=100.0))

    verdict = latency.compare("voice", "direct", "gateway")

    # Better than comparing against nothing and calling it an improvement.
    assert verdict["ready"] is False
    assert "gateway" in verdict["detail"]
