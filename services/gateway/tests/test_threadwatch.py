"""A supervisor thread that dies should cost a health check, not silence.

`smart_room_supervisor` died twice on this machine. It is the only thing that
restarts the room runtime, its liveness check ends in `sock.recv`, and the
plugin catches a socket error around the restart but not around the check. The
Gateway stayed up and every surface went on reporting the room as fine.
"""

from __future__ import annotations

import threading

import pytest

from marvi_gateway import threadwatch


@pytest.fixture(autouse=True)
def _empty():
    threadwatch.forget()
    yield
    threadwatch.forget()


def test_a_supervisory_thread_is_reported_as_degraded() -> None:
    threadwatch.died("smart_room_supervisor", OSError("connection reset"))
    assert threadwatch.degraded() == ["smart_room_supervisor"]
    row = threadwatch.losses()[0]
    assert row["thread"] == "smart_room_supervisor"
    assert "OSError" in row["error"]


def test_an_ordinary_thread_is_recorded_but_not_degrading() -> None:
    # Worth having in the record; not worth telling somebody their room is
    # broken over.
    threadwatch.died("ThreadPoolExecutor-3_1", ValueError("nope"))
    assert threadwatch.degraded() == []
    assert len(threadwatch.losses()) == 1


def test_a_thread_that_came_back_is_not_a_loss() -> None:
    """Restarted under the same name is recovered, not gone.

    The record is permanent and the loss is not, so the live thread set decides
    -- otherwise one crash marks a subsystem broken for the rest of the run.
    """
    running = threading.Event()
    thread = threading.Thread(target=running.wait, name="smart_room_supervisor")
    thread.start()
    try:
        threadwatch.died("smart_room_supervisor", OSError("reset"))
        assert threadwatch.degraded() == []
    finally:
        running.set()
        thread.join()
    assert threadwatch.degraded() == ["smart_room_supervisor"]


def test_the_record_is_bounded() -> None:
    for index in range(threadwatch.KEEP + 10):
        threadwatch.died(f"marvi-worker-{index}", OSError("x"))
    assert len(threadwatch.losses()) == threadwatch.KEEP


def test_recording_never_raises() -> None:
    threadwatch.died("", None)
    threadwatch.died(None, None)  # type: ignore[arg-type]
    assert len(threadwatch.losses()) == 2


def test_the_excepthook_records_what_it_logs() -> None:
    """The hook and the record must not drift apart.

    The hook already logged a CRITICAL and that was the whole response; this
    asserts the second half exists, because a health check that silently stops
    being fed is worse than one that was never wired.
    """
    import inspect

    from marvi_gateway import logs

    source = inspect.getsource(logs)
    assert "threadwatch.died(" in source, "the thread excepthook no longer records losses"
