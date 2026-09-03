"""The warm pool waiting its turn.

`prewarm` runs on a process created at the moment a job took the warm one --
which is the moment somebody started talking. Loading a second 2.3 GB
checkpoint onto the same card right then cost the live recogniser about a
fifth of its speed, measured: 157 ms per flush to 187 ms, worst 203 ms.
"""

from __future__ import annotations

import os
import time

import pytest

from marvi_agent import oncall


@pytest.fixture(autouse=True)
def _elsewhere(tmp_path, monkeypatch):
    monkeypatch.setattr(oncall, "MARKER", tmp_path / "state" / "voice-call.live")
    yield


def test_no_marker_means_nobody_is_talking() -> None:
    assert oncall.busy() is False
    # And a prewarm on an idle machine does not pause at all.
    assert oncall.wait_until_free() == 0.0


def test_a_live_call_is_seen_from_another_process() -> None:
    live = oncall.Marker()
    live.start()
    try:
        assert oncall.busy() is True
        # The pid is in it, so a stuck marker can be traced to something.
        assert oncall.MARKER.read_text(encoding="utf-8") == str(os.getpid())
    finally:
        live.stop()
    # Removed on the way out rather than left to expire: the replacement
    # should start loading when the call ends, not ten seconds later.
    assert oncall.busy() is False
    assert not oncall.MARKER.exists()


def test_a_job_that_died_stops_holding_the_pool(monkeypatch) -> None:
    """Freshness, not existence.

    A crashed job cannot delete its own marker. If the file alone meant "busy",
    one crash would leave every future prewarm waiting for a call that ended --
    so the pool would never refill again until somebody deleted a file.
    """
    oncall.MARKER.parent.mkdir(parents=True, exist_ok=True)
    oncall.MARKER.write_text("31816", encoding="utf-8")
    old = time.time() - (oncall.STALE + 5)
    os.utime(oncall.MARKER, (old, old))

    assert oncall.busy() is False
    assert oncall.wait_until_free() == 0.0


def test_the_wait_ends_when_the_call_does(monkeypatch) -> None:
    calls = {"n": 0}

    def answers(*_a: object) -> bool:
        calls["n"] += 1
        # Busy for the first few looks, then the call is over.
        return calls["n"] <= 3

    monkeypatch.setattr(oncall, "busy", answers)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    oncall.wait_until_free()
    # Looked four times: busy, busy, busy, free. It stops at the first look
    # that says the call is over rather than sitting out the rest of a poll.
    assert calls["n"] == 4


def test_it_gives_up_rather_than_wedging_the_pool(monkeypatch) -> None:
    # Staleness covers a crash; this covers the other shape, where something
    # keeps the mark fresh forever. A pool that never refills is worse than a
    # call that shares the card.
    monkeypatch.setattr(oncall, "busy", lambda: True)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    waited = oncall.wait_until_free(patience=0.05)
    assert waited >= 0.05


def test_the_beat_keeps_it_fresh(monkeypatch) -> None:
    monkeypatch.setattr(oncall, "BEAT", 0.02)
    live = oncall.Marker()
    live.start()
    try:
        first = oncall.MARKER.stat().st_mtime_ns
        deadline = time.monotonic() + 2.0
        while oncall.MARKER.stat().st_mtime_ns == first and time.monotonic() < deadline:
            time.sleep(0.02)
        assert oncall.MARKER.stat().st_mtime_ns != first, "the marker went stale mid-call"
    finally:
        live.stop()


def test_the_wait_fits_inside_what_the_worker_allows() -> None:
    """The wait happens inside `prewarm`, on the worker's initialisation clock.

    That is the trap this pair of numbers exists to close. `prewarm` waits for
    the call, and LiveKit runs `prewarm` under `initialize_process_timeout` --
    so the wait spends the process's budget for starting up. At 180 seconds,
    a call longer than three minutes killed the spare two seconds before it
    finished loading:

        15:03:02.44  prewarm: a call is in progress; waiting
        15:05:53.57  prewarm: the call ended after 171.1s; loading now
        15:06:02.50  error initializing process ... TimeoutError   <- 180.06s

    and the card then loaded Kyutai twice more, back to back, for the process
    that died and its replacement.
    """
    from marvi_agent import session

    assert oncall.INIT_BUDGET > oncall.PATIENCE, "the wait cannot fit in the budget"
    # And room for the slowest prewarm ever measured here, 48.6s.
    assert oncall.INIT_BUDGET - oncall.PATIENCE >= 120.0

    # And the worker has to actually be using it. Two constants that agree
    # with each other and not with the AgentServer would be the same bug,
    # with a passing test on top.
    assert session.server._initialize_process_timeout == oncall.INIT_BUDGET
    # Comfortably past the call lengths that killed it: 171s of waiting had
    # 9 seconds left of 180.
    assert oncall.INIT_BUDGET >= 600.0


def test_a_call_that_starts_while_the_process_is_spawning_is_caught(monkeypatch) -> None:
    """The race the marker alone loses.

    LiveKit creates the replacement process the instant a job is assigned, so
    the replacement's first look and the job writing its mark happen together.
    Marking the call first in the entrypoint wins by a couple of hundred
    milliseconds; it does not make the race go away. Live, the marker lost:

        15:39:03.86  job starting, process already warm
        15:39:04.0   the replacement begins loading Kyutai
        15:39:16.34  stt: kyutai ready in 12.3s

    -- twelve seconds of checkpoint loading through the opening turn, and no
    "waiting" line anywhere, because by the time the mark existed the
    replacement had already looked.
    """
    looks = {"n": 0}

    def appears_on_the_second_look() -> bool:
        looks["n"] += 1
        # Absent on the first look, present on the second, gone by the third.
        return looks["n"] == 2

    monkeypatch.setattr(oncall, "GRACE", 0.0)
    monkeypatch.setattr(oncall, "busy", appears_on_the_second_look)
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    oncall.wait_until_free()
    assert looks["n"] >= 3, "it committed the card after one look"


def test_an_idle_machine_still_only_pauses_briefly(monkeypatch) -> None:
    # The cost of that second look, paid on every genuinely cold prewarm.
    # It must stay a pause, not a wait.
    monkeypatch.setattr(oncall, "busy", lambda: False)
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)

    assert oncall.wait_until_free() == 0.0
    assert sum(slept) <= 2.0, f"an idle prewarm paused for {sum(slept)}s"
