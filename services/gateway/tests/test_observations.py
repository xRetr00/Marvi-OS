"""Keeping what Marvi did, so the next eval case does not need a person.

Every case in `docs/evals/` was found by reading a log by hand. This is the
evidence in one shape instead, and the tests that matter are the ones about it
never costing anything real: an observation that broke a turn, or filled a
disk, would be worse than no observation.
"""

from __future__ import annotations

import json

import pytest

from marvi_gateway import observations


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    monkeypatch.delenv(observations.SETTING, raising=False)
    return tmp_path


def test_rows_come_back_in_the_order_they_happened() -> None:
    observations.record("reply", said="first")
    observations.record("reply", said="second")

    assert [row["said"] for row in observations.read("reply")] == ["first", "second"]


def test_one_kind_can_be_read_without_the_others() -> None:
    observations.record("reply", said="spoken")
    observations.record("tool", event="call", name="room_state")

    assert [row["kind"] for row in observations.read("tool")] == ["tool"]


def test_recording_never_raises(monkeypatch) -> None:
    """It is called from a live turn. Anything it does must be survivable."""

    def broken(*_args, **_kwargs):
        raise OSError("disk is gone")

    monkeypatch.setattr(observations, "path", broken)
    observations.record("reply", said="still fine")  # must not raise


def test_a_corrupt_line_does_not_lose_the_file() -> None:
    """Written by appending from a live process, so a torn write is possible.
    One unreadable row must not take the rest with it."""
    observations.record("reply", said="before")
    with observations.path().open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    observations.record("reply", said="after")

    assert [row["said"] for row in observations.read("reply")] == ["before", "after"]


def test_long_text_is_cut_rather_than_stored_whole() -> None:
    """This is evidence for a suite, not a second copy of the conversation."""
    observations.record("reply", said="x" * 5_000)

    assert len(observations.read("reply")[0]["said"]) <= observations.MAX_TEXT


def test_credentials_never_reach_the_file() -> None:
    """It holds questions and excerpts, which means it can hold a mistake."""
    observations.record("reply", said="my key is sk-ant-api03-SECRETVALUE12345")

    written = observations.path().read_text(encoding="utf-8")
    assert "SECRETVALUE12345" not in written


def test_it_can_be_switched_off(monkeypatch) -> None:
    monkeypatch.setenv(observations.SETTING, "off")
    observations.record("reply", said="not written")

    assert observations.read() == []


def test_the_file_does_not_grow_without_limit(monkeypatch) -> None:
    """Marvi runs continuously. An unbounded append is a disk that fills."""
    monkeypatch.setattr(observations, "MAX_ROWS", 10)
    for index in range(25):
        observations.record("reply", said=f"turn {index}")

    dropped = observations.prune()
    rows = observations.read(limit=100)

    assert dropped == 15
    assert len(rows) == 10
    # The newest are what a suite wants; the oldest are what goes.
    assert rows[-1]["said"] == "turn 24"


def test_the_summary_says_whether_there_is_enough_to_learn_from() -> None:
    observations.record("reply", said="one")
    observations.record("tool", event="search", query="spotify", found=0)

    summary = observations.summarise()

    assert summary["kinds"] == {"reply": 1, "tool": 1}
    assert summary["enabled"] is True
    assert summary["rows"] == 2


def test_every_row_is_one_json_object() -> None:
    """The eval harnesses read this directly; the format is the contract."""
    observations.record("gate", door="ingest", offered=8, kept=2)

    line = observations.path().read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert parsed["kind"] == "gate" and parsed["offered"] == 8
    assert isinstance(parsed["at"], float)
