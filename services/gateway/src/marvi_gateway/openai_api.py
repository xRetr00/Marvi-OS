"""Marvi behind an OpenAI-shaped endpoint, for programs that only speak that.

Everything that talks to a local model speaks this dialect: Open WebUI, a
script with the `openai` package, an editor plugin, a shell alias. Answering it
costs one adapter and means none of them need to learn Marvi's own API -- and
what they reach is the *whole* Marvi, with her identity, memory, tools and
confirmation rules, rather than a bare model.

Three deliberate limits, because an adapter that pretends to be OpenAI is worse
than one that is honest about being Marvi:

* **One conversation per caller.** `user` in the request names a thread, so a
  script keeps its own history and two scripts do not share one. No `user`
  means the shared `api` thread.
* **Only the last user message is sent.** Marvi keeps her own history; replaying
  a client's would double it. A client that sends a whole transcript gets an
  answer to its newest message, which is what it wanted anyway.
* **`model` is ignored, and says so.** The model is whatever the Models page
  chose; a caller naming `gpt-4o` is telling Marvi something she has no way to
  honour, and silently answering as though she had is the kind of lie that
  wastes an afternoon.

Loopback plus `localauth` only -- this is Marvi's whole tool surface, and the
guard that stands in front of the provider credential stands in front of this.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import uuid4

#: What `GET /v1/models` answers. One model: this Marvi.
MODEL_ID = "marvi"

#: The thread a caller that did not name itself talks in.
DEFAULT_USER = "api"


def thread_name(user: str) -> str:
    """The conversation title for one caller."""
    clean = " ".join((user or "").split())[:40] or DEFAULT_USER
    return f"API · {clean}"


def last_user_message(messages: Any) -> str:
    """The newest thing the caller actually said."""
    if not isinstance(messages, list):
        return ""
    for row in reversed(messages):
        if not isinstance(row, dict) or row.get("role") != "user":
            continue
        content = row.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            # The multimodal shape: take the text parts, ignore the rest.
            text = " ".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
            return text.strip()
    return ""


def completion(reply: str, tokens: int, model: str = MODEL_ID) -> dict[str, Any]:
    """The non-streaming answer, in the shape every client parses."""
    return {
        "id": f"chatcmpl-{uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }
        ],
        # Only what Marvi actually counted. `prompt_tokens` is not broken out
        # because the turn's own accounting does not separate it per call, and
        # inventing a split is worse than reporting the total.
        "usage": {"prompt_tokens": 0, "completion_tokens": tokens, "total_tokens": tokens},
    }


def chunk(delta: str, done: bool = False, model: str = MODEL_ID, chunk_id: str = "") -> str:
    """One `data:` line of a streamed answer."""
    body = {
        "id": chunk_id or f"chatcmpl-{uuid4().hex[:24]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {} if done else {"content": delta},
                "finish_reason": "stop" if done else None,
            }
        ],
    }
    return "data: " + json.dumps(body) + chr(10) + chr(10)


def stream_lines(events: Iterator[dict[str, Any]], model: str = MODEL_ID) -> Iterator[str]:
    """Marvi's turn events as an OpenAI SSE stream.

    Reasoning is dropped rather than merged: it must not be spoken, must not
    reach a TTS, and a client that cannot tell it from the answer would put a
    model's private working in front of a user.
    """
    chunk_id = f"chatcmpl-{uuid4().hex[:24]}"
    for event in events:
        if delta := str(event.get("delta") or ""):
            yield chunk(delta, model=model, chunk_id=chunk_id)
        if event.get("done"):
            if error := str(event.get("error") or ""):
                yield chunk(f"\n\n[Marvi: {error}]", model=model, chunk_id=chunk_id)
            yield chunk("", done=True, model=model, chunk_id=chunk_id)
    yield "data: [DONE]" + chr(10) + chr(10)


async def as_async(lines: Iterator[str]) -> AsyncIterator[str]:
    for line in lines:
        yield line
