"""What she costs, and what she was doing at the time. See `accounting`."""

from __future__ import annotations

import json


def test_only_marvis_own_processes_are_counted() -> None:
    """The first version matched `"wake"` and counted Claude Code.

        7520  claude.exe --type=renderer ... --standalone-wake   506 MB

    Attributed to Marvi's wake word. A wrong number is worse than a missing
    one: it sends whoever reads it to look at the wrong process.
    """
    from marvi_gateway.accounting import _role

    assert _role("claude.exe --type=renderer --standalone-wake", "claude.exe") == ""
    assert _role("...\wake-host\marvi-wake-host.exe", "marvi-wake-host.exe") == "wake-word"
    # A common module name only counts from inside the install.
    assert _role("python -m runtime.app", "python.exe") == ""
    assert _role("...\Marvi-OS\install\python.exe -m runtime.app", "python.exe") == "room"
    assert _role("uvicorn marvi_gateway.app:app", "python.exe") == "gateway"
    assert _role("python -m marvi_agent.session start", "python.exe") == "agent"
    assert _role("python -m marvi_tts_voxtream.host", "python.exe") == "tts-voxtream"


def test_a_reading_says_what_she_was_doing(tmp_path) -> None:
    """A number without a phase is a fact; with one it is a bug report."""
    from marvi_gateway.accounting import Accountant

    books = Accountant(tmp_path / "resources.jsonl")
    books.told(moment="starting", phase="ready")
    reading = books.look(deep=False)

    assert reading.doing.moment == "starting"
    assert reading.ram_total_mb > 0, "the machine's own memory should always read"
    # Cheap readings do not go looking for per-process video memory, and say so
    # rather than reporting a stale number as current.
    assert reading.deep is False
    assert all(one.vram_mb is None for one in reading.processes)


def test_the_ledger_survives_a_restart(tmp_path) -> None:
    """The commonest reason to go looking is that something crashed."""
    from marvi_gateway.accounting import Accountant

    path = tmp_path / "resources.jsonl"
    first = Accountant(path)
    first.told(moment="game", busy_with="FC 26", low_resource=True)
    first.look(deep=False)

    again = Accountant(path)
    history = again.history()

    assert len(history) == 1
    assert history[0]["doing"]["busy_with"] == "FC 26"
    assert history[0]["doing"]["low_resource"] is True
    # And it is readable without this code, which is the point of a file.
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])["doing"]["moment"] == "game"


def test_the_summary_splits_by_what_she_was_doing(tmp_path) -> None:
    """Averaged over a day she uses three gigabytes.

    Split by what she was doing, she uses three gigabytes *while idle*, which
    is a different sentence and the one that gets something fixed.
    """
    from marvi_gateway.accounting import Accountant

    books = Accountant(tmp_path / "resources.jsonl")
    books.told(moment="starting")
    books.look(deep=False)
    books.told(moment="game", busy_with="FC 26")
    books.look(deep=False)

    doings = [row["doing"] for row in books.summary()["by_phase"]]

    assert "starting" in doings
    assert "game" in doings


def test_a_reading_asks_what_she_is_doing_rather_than_waiting_to_be_told(tmp_path) -> None:
    """The first live ledger labelled fifteen of twenty-seven `unknown`.

    Pushing alone was not enough: `told` fires when something changes, and the
    thirty-second timer keeps firing in between. A reading with no phase is a
    number nobody can use.
    """
    from marvi_gateway.accounting import Accountant

    books = Accountant(tmp_path / "resources.jsonl")
    assert books.look(deep=False).doing.phase == "unknown"

    books.reads_phase = lambda: "listening"
    assert books.look(deep=False).doing.phase == "listening"

    # A phase that cannot be read is not a reason to lose the reading.
    def broken() -> str:
        raise RuntimeError("the store is gone")

    books.reads_phase = broken
    assert books.look(deep=False).doing.phase == "listening"
