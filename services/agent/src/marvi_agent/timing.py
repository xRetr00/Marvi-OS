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
import json
import logging
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


class RecoveringStream(llm.LLMStream):
    """The model's stream, with a tool call it typed out turned back into a call.

    `tts_node` stops her *speaking* a call written as text, and that was half
    the fix: the tool still never ran, so the turn ended on whatever came
    before the markup and the thing she was about to do did not happen.

    This lives on the LLM stream rather than in `llm_node` on purpose. An
    `llm_node` override is forbidden by `test_every_turn_reaches_the_model...`:
    a wake gate there once returned None and discarded questions silently. This
    never gates -- every chunk in produces output out -- but it does not need
    to touch that method to do its job, so it does not.

    Held while the reply could still be a call, released the moment it is
    plainly prose, so ordinary speech streams exactly as it did.
    """

    def __init__(self, inner: llm.LLMStream) -> None:
        # A proxy, like `TimedStream`: the inner stream already runs its task.
        self._inner = inner
        self._held: list[str] = []
        self._withholding = True
        self._chunk_id = ""
        self._pending: list[Any] = []
        self._done = False

    async def _run(self) -> None:
        raise NotImplementedError("RecoveringStream proxies a stream that is already running")

    def __aiter__(self) -> RecoveringStream:
        return self

    def _text(self, content: str) -> Any:
        return llm.ChatChunk(
            id=self._chunk_id, delta=llm.ChoiceDelta(role="assistant", content=content)
        )

    async def __anext__(self) -> Any:
        from . import tool_call_prose

        if self._pending:
            return self._pending.pop(0)
        if self._done:
            raise StopAsyncIteration
        while True:
            try:
                chunk = await self._inner.__anext__()
            except StopAsyncIteration:
                self._done = True
                return self._finish(tool_call_prose)
            delta = getattr(chunk, "delta", None)
            text = getattr(delta, "content", None) if delta is not None else None
            if not self._withholding or not text:
                return chunk
            self._chunk_id = getattr(chunk, "id", "") or self._chunk_id
            self._held.append(text)
            if not tool_call_prose.might_be_starting("".join(self._held)):
                self._withholding = False
                released, self._held = "".join(self._held), []
                return self._text(released)

    def _finish(self, tool_call_prose: Any) -> Any:
        """The end of the stream, with anything still held resolved."""
        if not self._held:
            raise StopAsyncIteration
        said, self._held = "".join(self._held), []
        meant = tool_call_prose.recover(said)
        if meant is None:
            # Not a call, or not one that can be read. Released as text;
            # `tts_node` drops anything from a call opener onward, so the worst
            # case is silence, never XML read aloud.
            return self._text(said)
        logging.getLogger("marvi.voice").warning(
            "recovered a tool call the model spoke as text: %s", meant["name"]
        )
        return llm.ChatChunk(
            id=self._chunk_id,
            delta=llm.ChoiceDelta(
                role="assistant",
                tool_calls=[
                    llm.FunctionToolCall(
                        name=str(meant["name"]),
                        arguments=json.dumps(meant["arguments"]),
                        call_id=f"recovered-{time.time_ns()}",
                    )
                ],
            ),
        )

    async def aclose(self) -> None:
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
        return TimedStream(RecoveringStream(self._inner.chat(**kwargs)), sample, started)

    async def aclose(self) -> None:
        await self._inner.aclose()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
