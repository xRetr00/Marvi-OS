"""Staging memory before the turn ends, so preemptive generation survives.

LiveKit keeps a speculative reply only if the chat context is unchanged when
the turn is confirmed. Adding memory in `on_user_turn_completed` changed it on
every turn, so every speculation was discarded and the feature was off.

The mechanism was checked separately against the real `ChatContext`: today's
ordering invalidates, staging survives, doing both invalidates, and replacing a
stale block survives. These test the *implementation* of that -- which is a
different thing, and was missing when the change was first called done.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from marvi_agent import session as session_module


class FakeContext:
    """Enough of `ChatContext` to see what was built."""

    def __init__(self, items=None):
        self.items = list(items or [])

    def copy(self):
        return FakeContext(self.items)

    def add_message(self, role, content):
        self.items.append(_Item(role, content))


class _Item:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class FakeAgent:
    def __init__(self):
        self.chat_ctx = FakeContext()
        self.installed: list[FakeContext] = []

    async def update_chat_ctx(self, context):
        self.chat_ctx = context
        self.installed.append(context)


def _loop():
    """A loop on its own thread, because the prefetch runs on one."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    return loop


def _settle(prefetch, agent, tries=200):
    for _ in range(tries):
        if agent.installed and prefetch._installed:
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def staged(monkeypatch):
    """A prefetch wired to a fake agent, with recall stubbed out."""
    monkeypatch.setenv(session_module.SPECULATE, "on")
    monkeypatch.setattr(
        session_module, "_recall", lambda text, read=False: f"# What you remember\n\n- about {text}"
    )
    loop = _loop()
    agent = FakeAgent()
    prefetch = session_module._Prefetch()
    prefetch.attach(agent, loop)
    yield prefetch, agent
    loop.call_soon_threadsafe(loop.stop)


def test_memory_reaches_the_agent_context_before_the_turn_ends(staged) -> None:
    """The whole point: it has to be there when the speculation snapshots it,
    not added afterwards by the turn hook."""
    prefetch, agent = staged

    prefetch.begin("what computer am I running you on")

    assert _settle(prefetch, agent), "nothing was staged"
    blocks = [item for item in agent.chat_ctx.items if item.role == "system"]
    assert len(blocks) == 1
    assert "what computer am I running you on" in str(blocks[0].content)


def test_a_second_sentence_replaces_the_first_block(staged) -> None:
    """A prefetch runs per sentence. Two left behind would put a stale
    question's memories in front of the next one -- worse than none, because
    they look current."""
    prefetch, agent = staged
    prefetch.begin("what computer am I running you on")
    assert _settle(prefetch, agent)

    prefetch._query = ""  # let a different sentence through
    prefetch.begin("what games do I play on it")
    for _ in range(200):
        if len(agent.installed) > 1:
            break
        time.sleep(0.01)

    blocks = [item for item in agent.chat_ctx.items if item.role == "system"]
    assert len(blocks) == 1, "the previous block was left behind"
    assert "what games do I play" in str(blocks[0].content)


def test_the_turn_knows_the_memory_is_already_there(staged) -> None:
    """`staged()` is what stops `on_user_turn_completed` adding a second copy.
    Adding it in both places invalidates the speculation -- verified against
    the real ChatContext -- so this is the check that makes the whole thing
    work rather than silently undo itself."""
    prefetch, agent = staged
    prefetch.begin("what computer am I runni")
    assert _settle(prefetch, agent)

    assert prefetch.staged("what computer am I running you on") is True
    # Consumed: the next turn is a different sentence.
    assert prefetch.staged("what computer am I running you on") is False


def test_a_different_sentence_does_not_claim_the_staged_block(staged) -> None:
    prefetch, agent = staged
    prefetch.begin("what computer am I runni")
    assert _settle(prefetch, agent)

    assert prefetch.staged("tell me about the bakery") is False


def test_a_stale_block_is_not_claimed(staged, monkeypatch) -> None:
    """Same freshness rule as `take`: a block older than the window belongs to
    a sentence that has already been answered."""
    prefetch, agent = staged
    prefetch.begin("what computer am I runni")
    assert _settle(prefetch, agent)
    monkeypatch.setattr(
        session_module.time, "monotonic", lambda: prefetch._at + prefetch.FRESH + 1
    )

    assert prefetch.staged("what computer am I running you on") is False


def test_switching_it_off_restores_the_old_behaviour(monkeypatch) -> None:
    """`MARVI_SPECULATIVE_RECALL=off` must stage nothing and claim nothing, so
    the turn hook adds the block exactly as it used to."""
    monkeypatch.setenv(session_module.SPECULATE, "off")
    monkeypatch.setattr(session_module, "_recall", lambda text, read=False: "# What you remember")
    loop = _loop()
    agent = FakeAgent()
    prefetch = session_module._Prefetch()
    prefetch.attach(agent, loop)
    try:
        prefetch.begin("what computer am I running you on")
        time.sleep(0.3)

        assert agent.installed == []
        assert prefetch.staged("what computer am I running you on") is False
    finally:
        loop.call_soon_threadsafe(loop.stop)


def test_a_prefetch_with_no_agent_still_works(monkeypatch) -> None:
    """Staging is an addition. Without an agent attached the prefetch must
    behave exactly as it did before, so `take` still answers."""
    monkeypatch.setenv(session_module.SPECULATE, "on")
    monkeypatch.setattr(session_module, "_recall", lambda text, read=False: "block")
    prefetch = session_module._Prefetch()

    prefetch.begin("what computer am I running you on")
    for _ in range(200):
        if prefetch._block:
            break
        time.sleep(0.01)

    assert prefetch.take("what computer am I running you on") == "block"


def test_preemptive_generation_follows_the_same_switch() -> None:
    """The two are one decision: staging exists so the speculation survives,
    and the speculation is only safe because staging happens."""
    import inspect

    source = inspect.getsource(session_module)
    assert 'preemptive_generation={"enabled": eager()}' in source
