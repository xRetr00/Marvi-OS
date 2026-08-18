"""Timing a voice turn, so Phase 12 can be judged rather than argued about.

The plan says route every LLM call through the Gateway and stop if voice
regresses. That needs a number from before the change and a number from after,
measured the same way, on the same machine, through the same session.

**First token is the number.** A voice turn starts speaking as soon as tokens
arrive, so the time to the first one is what a person experiences as Marvi
being quick. Total response time barely shows up: the words are already coming.
A change that improves total and worsens first token has made voice worse, and
measuring the wrong one would hide exactly that.

This wraps whatever LLM the session was given, so the same wrapper measures the
current direct path and the Gateway path that replaces it. `path` is the label
that tells them apart in the recording.
"""

from __future__ import annotations

import contextlib
import os
import time
from typing import Any

import httpx
from livekit.agents import llm

RECORD_TIMEOUT = 2.0


def gateway_base_url() -> str:
    return os.environ.get("MARVI_GATEWAY_URL", "http://127.0.0.1:8765").rstrip("/")


def _report(sample: dict[str, Any]) -> None:
    """Send one sample to the Gateway, which owns the recording.

    Fire and forget, after the turn is finished. The agent could append to the
    file itself — both processes know MARVI_HOME — but two writers on one file
    is a race nobody needs for a diagnostic, and the Gateway already owns it.

    Never raises. A turn that worked must not be reported as broken because the
    measurement of it could not be filed.
    """
    with contextlib.suppress(Exception):
        httpx.post(f"{gateway_base_url()}/latency", json=sample, timeout=RECORD_TIMEOUT)


class TimedStream(llm.LLMStream):
    """Delegates to a real stream, noting when the first chunk arrives."""

    def __init__(self, inner: llm.LLMStream, sample: dict[str, Any], started: float) -> None:
        # Deliberately not calling super().__init__: this is a proxy, not a
        # stream of its own, and LLMStream's constructor starts a task that
        # would duplicate the inner one's work.
        self._inner = inner
        self._sample = sample
        self._started = started
        self._reported = False

    async def _run(self) -> None:
        """Never called.

        `LLMStream` declares this abstract and its constructor starts it as a
        task. This proxies a stream that is already running its own, so the
        constructor is skipped and so is this. It exists to satisfy the ABC.
        """
        raise NotImplementedError("TimedStream proxies a stream that is already running")

    def __aiter__(self) -> TimedStream:
        return self

    async def __anext__(self) -> Any:
        try:
            chunk = await self._inner.__anext__()
        except StopAsyncIteration:
            self._finish()
            raise
        except Exception as exc:
            self._sample["error"] = f"{type(exc).__name__}: {exc}"[:200]
            self._finish()
            raise
        if self._sample.get("first_token_ms") is None:
            self._sample["first_token_ms"] = (time.perf_counter() - self._started) * 1000
        return chunk

    def _finish(self) -> None:
        if self._reported:
            return
        self._reported = True
        # Set rather than assumed: a turn that failed before its first chunk
        # has no first token, and a consumer reading the sample should find the
        # key saying so rather than not finding the key.
        self._sample.setdefault("first_token_ms", None)
        self._sample["total_ms"] = (time.perf_counter() - self._started) * 1000
        _report(self._sample)

    async def aclose(self) -> None:
        # A turn the user interrupted is still a turn worth timing — barge-in is
        # normal on voice, and dropping those samples would bias the result
        # towards the slow ones nobody cut short.
        self._finish()
        await self._inner.aclose()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class TimedLLM(llm.LLM):
    """An LLM that behaves exactly like the one it wraps, and records the wait."""

    def __init__(self, inner: llm.LLM, path: str, provider: str = "", model: str = "") -> None:
        super().__init__()
        self._inner = inner
        self._path = path
        self._provider = provider
        self._model = model

    @property
    def model(self) -> str:
        return getattr(self._inner, "model", self._model)

    def chat(self, **kwargs: Any) -> TimedStream:
        started = time.perf_counter()
        sample = {
            "surface": "voice",
            "path": self._path,
            "provider": self._provider,
            "model": self._model,
            "first_token_ms": None,
            "total_ms": None,
        }
        return TimedStream(self._inner.chat(**kwargs), sample, started)

    async def aclose(self) -> None:
        await self._inner.aclose()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
