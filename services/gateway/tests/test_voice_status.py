"""What the status bar says about voice, and when it should say nothing.

The readiness flag answers one question: would a *new* call be answered right
now. During a call the honest answer is no -- the warm process was taken and
its replacement waits for the GPU until the call ends -- and reporting that as
the state of voice put

    WARMING UP  Loading the speech models

across the top of a working conversation, for the whole five minutes of it.
"""

from __future__ import annotations

import time

import pytest

from marvi_gateway import conversation
from marvi_gateway.app import voice_state


@pytest.fixture(autouse=True)
def _no_call():
    conversation.report(False)
    yield
    conversation.report(False)


def test_a_registered_worker_is_simply_ready() -> None:
    state = voice_state(worker_ready=True, detail="", in_a_call=False)
    assert state.state == "ready"


def test_a_loading_worker_says_so_when_nothing_is_happening() -> None:
    # The reason the flag exists: a Join pressed while the worker is loading
    # opens a session that nothing ever joins, and LiveKit does not dispatch
    # again when the worker turns up.
    state = voice_state(
        worker_ready=False, detail="loading speech models for the next call", in_a_call=False
    )
    assert state.state == "starting"
    assert "loading speech models" in state.detail


def test_a_live_call_is_not_a_worker_that_is_still_starting() -> None:
    """The five minutes of "WARMING UP" over a working conversation."""
    state = voice_state(
        worker_ready=False, detail="loading speech models for the next call", in_a_call=True
    )
    assert state.state == "ready", "the banner is back over a live call"
    # The pool's state is not hidden, just demoted to where it belongs: it
    # still tells you the next join will be slower.
    assert "in a call" in state.detail


def test_a_call_that_stopped_reporting_is_not_believed() -> None:
    """The banner now rides on the same flag that mutes the mind.

    A renderer that dies mid-call would otherwise leave the Gateway believing a
    conversation is running for the rest of its life -- silencing the mind, and
    now also claiming voice is fine when nothing is there. It expires, which is
    why the desktop has to keep saying so; see `SAY_AGAIN` in the voice store.
    """
    conversation.report(True)
    assert conversation.active() is True

    conversation._at = time.monotonic() - (conversation.TRUSTED_FOR + 1)
    assert conversation.active() is False
