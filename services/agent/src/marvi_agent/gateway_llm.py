"""LiveKit's LLM interface, answered by Marvi's Gateway.

The voice path used to build `livekit.plugins.openai.LLM` and talk to the
provider itself. The Gateway chose *which* provider, and then saw nothing: no
fallback when one failed, no cooldown when a credential was rejected, no record
of what the turn cost. Chat and Mind had all three because they went through
`ProviderClient`; voice and vision did not.

This is the seam. LiveKit keeps the turn — voice activity, end-of-utterance,
barge-in, all the parts that are genuinely hard and that it is good at. It just
stops owning the provider.

Implementing `llm.LLM` is the designed way in: LiveKit's own plugins are
implementations of the same interface, so this is using the framework rather
than working around it.

The cost is one loopback hop per turn, and the reason `/llm` streams is that a
buffered response would turn first-token latency into whole-response latency —
the exact thing voice cannot afford. `latency.compare` is the gate on whether
the hop was worth it.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from livekit.agents import llm
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

#: Generous: it covers a slow model thinking, not a slow network. The Gateway
#: is on loopback, and a provider that stalls is a provider the Gateway will
#: put on cooldown anyway.
TURN_TIMEOUT = 120.0


def gateway_base_url() -> str:
    return os.environ.get("MARVI_GATEWAY_URL", "http://127.0.0.1:8765").rstrip("/")


def _as_messages(chat_ctx: Any) -> list[dict[str, Any]]:
    """LiveKit's ChatContext, as the wire format every provider mode starts from.

    Kept small and defensive: the context is LiveKit's type and its shape has
    moved between versions, so this reads what it needs and ignores the rest
    rather than mirroring a structure that is not ours.
    """
    messages: list[dict[str, Any]] = []
    for item in getattr(chat_ctx, "items", None) or []:
        role = getattr(item, "role", None)
        if role not in ("system", "user", "assistant"):
            continue
        content = getattr(item, "text_content", None)
        if callable(content):
            content = content()
        if content is None:
            parts = getattr(item, "content", None) or []
            content = " ".join(part for part in parts if isinstance(part, str))
        text = (content or "").strip()
        if text:
            messages.append({"role": role, "content": text})
    return messages


class GatewayStream(llm.LLMStream):
    """Server-sent events from the Gateway, as LiveKit chat chunks."""

    def __init__(self, gateway: GatewayLLM, *, chat_ctx: Any, tools: Any, conn_options: Any):
        super().__init__(gateway, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
        self._gateway = gateway

    async def _run(self) -> None:
        payload = {
            "messages": _as_messages(self._chat_ctx),
            "job": self._gateway.job,
            "surface": self._gateway.surface,
        }
        async with httpx.AsyncClient(timeout=TURN_TIMEOUT) as client, client.stream(
            "POST", f"{gateway_base_url()}/llm", json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                piece = _read(line)
                if piece is None:
                    continue
                if piece.get("error"):
                    # Surfaced rather than swallowed: a turn that failed
                    # should say so out loud, not end in silence that looks
                    # like Marvi ignoring the user.
                    raise RuntimeError(piece["error"])
                delta = piece.get("delta")
                if delta:
                    self._event_ch.send_nowait(
                        llm.ChatChunk(
                            id=piece.get("id", ""),
                            delta=llm.ChoiceDelta(role="assistant", content=delta),
                        )
                    )


def _read(line: str) -> dict[str, Any] | None:
    text = (line or "").strip()
    if not text.startswith("data:"):
        return None
    body = text[5:].strip()
    if not body or body == "[DONE]":
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


class GatewayLLM(llm.LLM):
    """The LLM the voice session uses. Every call goes through `ProviderClient`."""

    def __init__(self, job: str = "main", surface: str = "voice") -> None:
        super().__init__()
        self.job = job
        self.surface = surface

    @property
    def model(self) -> str:
        # The Gateway decides. Saying so is better than caching a name that the
        # user may change in the control centre mid-session.
        return "gateway"

    def chat(
        self,
        *,
        chat_ctx: Any,
        tools: Any = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        **_ignored: Any,
    ) -> GatewayStream:
        return GatewayStream(
            self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options
        )
