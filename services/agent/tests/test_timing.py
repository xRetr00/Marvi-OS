"""The timing wrapper.

If this measures the wrong thing, Phase 12 is decided on a wrong number. So the
properties worth pinning are: first token is not last token, an interrupted
turn still counts, and nothing here can break a turn.
"""

from __future__ import annotations

import asyncio

import pytest

from marvi_agent import timing


class FakeStream:
    """Stands in for an LLMStream: yields chunks with a gap before the first."""

    def __init__(self, chunks, first_delay=0.05, gap=0.0, fail=None):
        self._chunks = list(chunks)
        self._first_delay = first_delay
        self._gap = gap
        self._fail = fail
        self._sent = 0
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._fail and self._sent == 0:
            raise self._fail
        if not self._chunks:
            raise StopAsyncIteration
        await asyncio.sleep(self._first_delay if self._sent == 0 else self._gap)
        self._sent += 1
        return self._chunks.pop(0)

    async def aclose(self):
        self.closed = True


@pytest.fixture
def recorded(monkeypatch):
    samples = []
    monkeypatch.setattr(timing, "_report", samples.append)
    return samples


@pytest.mark.asyncio
async def test_first_token_is_timed_from_the_request_not_the_end(recorded) -> None:
    stream = timing.TimedStream(
        FakeStream(["a", "b", "c"], first_delay=0.05, gap=0.05), {"surface": "voice"}, __import__("time").perf_counter()
    )
    async for _ in stream:
        pass

    sample = recorded[0]
    # Three chunks, 50ms apart: first token near 50ms, total near 150ms. If the
    # two were the same number this wrapper would be measuring the wrong thing.
    assert 30 <= sample["first_token_ms"] <= 120
    assert sample["total_ms"] > sample["first_token_ms"] + 40


@pytest.mark.asyncio
async def test_an_interrupted_turn_is_still_recorded(recorded) -> None:
    """Barge-in is normal on voice. Dropping those biases towards slow turns."""
    import time as _time

    stream = timing.TimedStream(FakeStream(["a", "b"]), {"surface": "voice"}, _time.perf_counter())
    await stream.__anext__()
    await stream.aclose()

    assert len(recorded) == 1
    assert recorded[0]["first_token_ms"] is not None


@pytest.mark.asyncio
async def test_a_turn_is_recorded_once_however_it_ends(recorded) -> None:
    import time as _time

    stream = timing.TimedStream(FakeStream(["a"]), {"surface": "voice"}, _time.perf_counter())
    async for _ in stream:
        pass
    await stream.aclose()

    assert len(recorded) == 1


@pytest.mark.asyncio
async def test_a_failed_turn_records_the_error_and_no_first_token(recorded) -> None:
    import time as _time

    stream = timing.TimedStream(
        FakeStream([], fail=RuntimeError("provider refused")), {"surface": "voice"}, _time.perf_counter()
    )
    with pytest.raises(RuntimeError):
        await stream.__anext__()

    assert "provider refused" in recorded[0]["error"]
    assert recorded[0]["first_token_ms"] is None


def test_reporting_never_raises(monkeypatch) -> None:
    """A turn that worked must not fail because its measurement could not file."""

    def refuse(*_args, **_kwargs):
        raise OSError("gateway down")

    monkeypatch.setattr(timing.httpx, "post", refuse)
    timing._report({"surface": "voice"})
