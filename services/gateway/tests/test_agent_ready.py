"""Whether voice is ready, as opposed to merely possible.

The Gateway reported voice "ready" once LiveKit was up and the speech models
were on disk. Neither says anything about the worker, which spends eighteen
seconds loading those models into the GPU before it registers -- and a job is
dispatched when the room is created, so a Join pressed inside that window gets
no agent and never will. The session sits there connected with nobody in it.
"""

from __future__ import annotations

import pytest

from marvi_gateway import agent_ready


@pytest.fixture(autouse=True)
def forget():
    agent_ready.forget()
    yield
    agent_ready.forget()


def test_a_gateway_that_has_just_started_knows_nothing() -> None:
    """Not "ready" by default. The optimistic default is the whole bug."""
    assert agent_ready.status()["ready"] is False


def test_the_worker_saying_it_registered_is_what_makes_voice_ready() -> None:
    agent_ready.set(True, "worker registered")

    live = agent_ready.status()
    assert live["ready"] is True
    assert live["detail"] == "worker registered"


def test_a_worker_that_went_back_to_loading_is_not_ready() -> None:
    """The Agent restarts and says so before it reloads its models."""
    agent_ready.set(True, "worker registered")
    agent_ready.set(False, "loading speech models")

    assert agent_ready.status()["ready"] is False


def test_how_long_ago_it_said_so_is_reported() -> None:
    """A worker that registered and then died without saying so leaves this
    stale. Reporting the age is honest about that rather than hiding it."""
    agent_ready.set(True)

    assert agent_ready.status()["age_seconds"] < 5
