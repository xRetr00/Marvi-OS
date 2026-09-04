"""Which model spent it, not just how much was spent.

An OpenRouter bill showed $3.03 against Claude Sonnet 4.5 -- a model nothing in
Marvi names and nobody had chosen. The ledger could say only that Marvi had
spent 34,688 input tokens that day, across some provider. Enough to prove by
arithmetic that it was not Marvi, and not enough to say what it was; the rest
had to be reconstructed from `providers.log`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from marvi_gateway.providers.base import Usage
from marvi_gateway.providers.usage import UsageLedger


@pytest.fixture
def ledger(tmp_path) -> UsageLedger:
    return UsageLedger(path=tmp_path / "usage.json")


def on(day: str) -> datetime:
    return datetime.fromisoformat(f"{day}T12:00:00+00:00").astimezone(UTC)


def test_each_model_is_counted_on_its_own(ledger: UsageLedger) -> None:
    ledger.record("openrouter", Usage(input=1000, output=100), model="qwen/qwen3.7-flash")
    ledger.record("openrouter", Usage(input=50, output=5), model="anthropic/claude-sonnet-5")
    ledger.record("openrouter", Usage(input=2000, output=200), model="qwen/qwen3.7-flash")

    models = {row["model"]: row for row in ledger.snapshot()["models"]}
    assert models["qwen/qwen3.7-flash"]["input"] == 3000
    assert models["anthropic/claude-sonnet-5"]["input"] == 50


def test_the_biggest_spender_is_first(ledger: UsageLedger) -> None:
    # The question is "what is spending this". The answer belongs at the top,
    # not wherever the alphabet happens to put it.
    ledger.record("openrouter", Usage(input=10), model="zzz-small")
    ledger.record("openrouter", Usage(input=90_000), model="aaa-expensive")

    assert ledger.snapshot()["models"][0]["model"] == "aaa-expensive"


def test_a_model_is_broken_down_by_day(ledger: UsageLedger) -> None:
    """Because the real question was "which model, on the day the bill jumped"."""
    ledger.record("openrouter", Usage(input=100), model="qwen", at=on("2026-09-01"))
    ledger.record("openrouter", Usage(input=900_000), model="sonnet-4.5", at=on("2026-09-02"))
    ledger.record("openrouter", Usage(input=200), model="qwen", at=on("2026-09-02"))

    by_model = {row["model"]: row for row in ledger.snapshot()["models"]}
    spike = {row["date"]: row["input"] for row in by_model["sonnet-4.5"]["daily"]}
    assert spike == {"2026-09-02": 900_000}
    everyday = {row["date"]: row["input"] for row in by_model["qwen"]["daily"]}
    assert everyday == {"2026-09-01": 100, "2026-09-02": 200}


def test_counters_are_never_lost_to_a_missing_model(ledger: UsageLedger) -> None:
    """An older voice worker sends no model, and its tokens still have to count.

    Dropping the record over a missing label would make the ledger wrong in the
    direction that matters -- under-reporting Marvi's own spend, which is the
    number the arithmetic above depended on.
    """
    ledger.record("openrouter", Usage(input=500, output=50))

    snapshot = ledger.snapshot()
    assert snapshot["providers"]["openrouter"]["input"] == 500
    assert snapshot["daily"][0]["input"] == 500
    # Unattributed rather than invented: no row claims those tokens.
    assert snapshot["models"] == []


def test_the_ledger_still_holds_only_counters(ledger: UsageLedger, tmp_path) -> None:
    # A model id is what was asked for, never what was said. Nothing about the
    # conversation may reach this file.
    ledger.record("openrouter", Usage(input=10), model="qwen/qwen3.7-flash")
    written = (tmp_path / "usage.json").read_text(encoding="utf-8")

    assert "qwen/qwen3.7-flash" in written
    for leak in ("prompt", "content", "message", "sk-", "Bearer"):
        assert leak not in written


def test_an_existing_ledger_without_models_still_reads(ledger: UsageLedger, tmp_path) -> None:
    # Everyone's ledger predates this. Reading one must not fail, and the first
    # new call must not have to rebuild history to be recorded.
    (tmp_path / "usage.json").write_text(
        '{"providers":{"openrouter":{"input":5,"output":1,"cached_input":0,"reasoning":0}}}',
        encoding="utf-8",
    )

    assert ledger.snapshot()["models"] == []
    ledger.record("openrouter", Usage(input=7), model="qwen")
    assert [row["model"] for row in ledger.snapshot()["models"]] == ["qwen"]
    assert ledger.snapshot()["providers"]["openrouter"]["input"] == 12
