"""Work Marvi handed off, brought back on its own.

`await_delegated` covers the case where the model chooses to wait. This covers
the case where it does not, which is most of them: the job finishes, nobody
asks, and the owner finds out by asking about work that completed four minutes
ago.
"""

from __future__ import annotations

import time

from marvi_agent.delegated import Delegated


def _settled(jobs: Delegated, tries: int = 200) -> list[dict]:
    for _ in range(tries):
        ready = jobs.take()
        if ready:
            return ready
        time.sleep(0.01)
    return []


def test_a_finished_job_is_waiting_for_the_next_turn(monkeypatch) -> None:
    import marvi_agent.delegated as module

    monkeypatch.setattr(module, "POLL_EVERY", 0.01)
    jobs = Delegated()
    jobs.attach(lambda job: {"state": "done", "summary": "added the docstring"})
    jobs.watch("j-1")

    ready = _settled(jobs)

    assert [row["job"] for row in ready] == ["j-1"]


def test_a_running_job_is_not_announced(monkeypatch) -> None:
    import marvi_agent.delegated as module

    monkeypatch.setattr(module, "POLL_EVERY", 0.01)
    jobs = Delegated()
    jobs.attach(lambda job: {"state": "running"})
    jobs.watch("j-2")
    time.sleep(0.1)

    assert jobs.take() == []


def test_it_is_said_once_and_then_it_is_in_the_conversation(monkeypatch) -> None:
    """Reading empties it. A block repeated every turn would have her announce
    the same finished job until the session ended."""
    import marvi_agent.delegated as module

    monkeypatch.setattr(module, "POLL_EVERY", 0.01)
    jobs = Delegated()
    jobs.attach(lambda job: {"state": "done", "summary": "renamed the thing"})
    jobs.watch("j-3")
    for _ in range(200):
        block = jobs.block()
        if block:
            break
        time.sleep(0.01)

    assert "renamed the thing" in block
    assert "j-3" in block
    assert jobs.block() == ""


def test_the_same_job_is_only_followed_once(monkeypatch) -> None:
    import marvi_agent.delegated as module

    monkeypatch.setattr(module, "POLL_EVERY", 0.01)
    asked: list[str] = []
    jobs = Delegated()

    def ask(job: str) -> dict:
        asked.append(job)
        return {"state": "running"}

    jobs.attach(ask)
    jobs.watch("j-4")
    jobs.watch("j-4")
    jobs.watch("j-4")
    time.sleep(0.1)

    # One follower, however many times it is asked for: three threads polling
    # one job is three times the requests for one answer.
    assert len(jobs._watching) == 1


def test_a_gateway_that_will_not_answer_never_reaches_a_turn(monkeypatch) -> None:
    """A poller cannot raise at anyone. The turn hook reads whatever landed,
    and nothing landing is the correct outcome of a Gateway being down."""
    import marvi_agent.delegated as module

    monkeypatch.setattr(module, "POLL_EVERY", 0.01)
    jobs = Delegated()

    def broken(job: str) -> dict:
        raise RuntimeError("the Gateway is not answering")

    jobs.attach(broken)
    jobs.watch("j-5")
    time.sleep(0.1)

    assert jobs.block() == ""


def test_nothing_is_followed_before_there_is_a_way_to_ask() -> None:
    jobs = Delegated()
    jobs.watch("j-6")

    assert jobs._watching == set()
