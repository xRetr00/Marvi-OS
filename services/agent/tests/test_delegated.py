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


def test_a_sub_agent_waiting_for_approval_is_said_once_and_still_followed(monkeypatch) -> None:
    """A sub-agent that needs the owner's yes is news now, not when it ends --
    it cannot end until somebody answers. Said once per request, and the job
    is followed on to its report."""
    import marvi_agent.delegated as module

    monkeypatch.setattr(module, "POLL_EVERY", 0.01)
    answers = iter(
        [
            {"state": "running"},
            {"state": "awaiting_approval", "token": "t1", "name": "Jarvi",
             "detail": "Jarvi wants to run computer_action close and is waiting."},
            {"state": "awaiting_approval", "token": "t1", "name": "Jarvi", "detail": "same"},
            {"state": "running"},
            {"state": "completed", "name": "Jarvi", "summary": "Notepad is closed."},
        ]
    )
    jobs = Delegated()
    jobs.attach(lambda job: next(answers, {"state": "completed", "summary": "Notepad is closed."}))
    jobs.watch("j-7")

    said: list[str] = []
    for _ in range(300):
        block = jobs.block()
        if block:
            said.append(block)
        if any("Notepad is closed." in one for one in said):
            break
        time.sleep(0.01)

    assert len(said) == 2
    assert "waiting" in said[0] and "delegate_approve" in said[0]
    assert "Notepad is closed." in said[1]


class FakeSession:
    """The four things `speak_up` reads from LiveKit's AgentSession, and the call it makes."""

    def __init__(self, agent_state: str = "listening", user_state: str = "listening") -> None:
        self.agent_state = agent_state
        self.user_state = user_state
        self.current_speech = None
        self.replies: list[str] = []

    def generate_reply(self, *, instructions: str) -> None:
        self.replies.append(instructions)


def _finished(monkeypatch, summary: str = "Notepad is closed.") -> Delegated:
    import marvi_agent.delegated as module

    monkeypatch.setattr(module, "POLL_EVERY", 0.01)
    jobs = Delegated()
    jobs.attach(lambda job: {"state": "completed", "name": "Jarvi", "summary": summary})
    return jobs


def test_she_is_told_the_moment_a_report_lands(monkeypatch) -> None:
    """The logs showed the report waiting for the owner to speak: finished at
    14:13:42, mentioned at 14:13:56 only because somebody said "Prezidon"."""
    landed: list[bool] = []
    jobs = _finished(monkeypatch)
    jobs.when_ready(lambda: landed.append(True))
    jobs.watch("j-8")
    for _ in range(200):
        if landed:
            break
        time.sleep(0.01)

    assert landed == [True]
    assert jobs.has_news()


def test_an_idle_marvi_speaks_up_by_herself(monkeypatch) -> None:
    from marvi_agent.delegated import speak_up

    jobs = _finished(monkeypatch)
    jobs.watch("j-9")
    for _ in range(200):
        if jobs.has_news():
            break
        time.sleep(0.01)
    session = FakeSession()

    assert speak_up(session, jobs, quiet_for=5.0) is True
    assert "Notepad is closed." in session.replies[0]
    # Said once: it is in the conversation now.
    assert not jobs.has_news()
    assert speak_up(session, jobs, quiet_for=5.0) is False


def test_she_never_talks_over_anybody(monkeypatch) -> None:
    """Busy in any way -- speaking, thinking, the owner mid-sentence or only
    just finished (their own turn is about to start) -- and the report waits."""
    from marvi_agent.delegated import speak_up

    jobs = _finished(monkeypatch)
    jobs.watch("j-10")
    for _ in range(200):
        if jobs.has_news():
            break
        time.sleep(0.01)

    for session, quiet in (
        (FakeSession(agent_state="speaking"), 5.0),
        (FakeSession(agent_state="thinking"), 5.0),
        (FakeSession(user_state="speaking"), 5.0),
        (FakeSession(), 0.3),
    ):
        assert speak_up(session, jobs, quiet_for=quiet) is False, session.__dict__
        assert session.replies == []
    busy = FakeSession()
    busy.current_speech = object()
    assert speak_up(busy, jobs, quiet_for=5.0) is False
    # Still waiting, for the next quiet moment or the owner's next turn.
    assert jobs.has_news()


def test_nothing_is_followed_before_there_is_a_way_to_ask() -> None:
    jobs = Delegated()
    jobs.watch("j-6")

    assert jobs._watching == set()
