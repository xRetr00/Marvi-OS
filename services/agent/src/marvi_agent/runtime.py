"""What the voice worker needs before it can speak.

No provider is named here. The Agent runs in its own Python environment and
must not carry a second copy of the provider table — two copies drift, and the
one that drifts is always the one the user did not edit.

Instead it asks the Gateway, over the same loopback channel it already uses for
tools, and gets back whatever the user configured in the control center. The
registry in `marvi_gateway.providers` stays the single source of truth.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx
from livekit.plugins import openai

RESOLVE_TIMEOUT = 8.0


class VoiceStackPendingError(RuntimeError):
    """Raised until the native-Windows STT/TTS bakeoff selects both adapters."""


class ProviderUnavailableError(RuntimeError):
    """The Gateway could not name a usable provider for the voice path."""


def gateway_base_url() -> str:
    return os.environ.get("MARVI_GATEWAY_URL", "http://127.0.0.1:8765").rstrip("/")


@dataclass(frozen=True, slots=True)
class AgentConfig:
    api_key: str
    model: str
    base_url: str
    provider: str = "unknown"
    #: The model's context window, as the provider reports it. Zero when it
    #: does not, in which case the reply cap stands on its own.
    context: int = 0
    #: Upstream routing, as configured. Empty for a provider that has none.
    route: dict = field(default_factory=dict)

    @classmethod
    def from_gateway(cls, client: httpx.Client | None = None) -> AgentConfig:
        http = client or httpx.Client(timeout=RESOLVE_TIMEOUT)
        try:
            response = http.get(f"{gateway_base_url()}/providers/voice")
            if response.status_code == 503:
                raise ProviderUnavailableError(
                    "No provider is configured. Connect one in the Marvi control center."
                )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"Marvi Gateway is unreachable: {exc}") from exc
        finally:
            if client is None:
                http.close()

        if not body.get("base_url") or not body.get("model"):
            raise ProviderUnavailableError("Gateway returned an incomplete provider")
        return cls(
            api_key=body.get("api_key") or "local",
            model=body["model"],
            base_url=body["base_url"],
            provider=body.get("provider", "unknown"),
            context=int(body.get("context") or 0),
            route=body.get("route") or {},
        )


#: How long a spoken reply may be, in tokens.
#:
#: Set because leaving it unset asks for the model's entire context. The plugin
#: sent no limit, so OpenRouter saw a request for 65,536 tokens, reserved credit
#: for all of them, and refused every voice turn:
#:
#:     402: This request requires more credits, or fewer max_tokens. You
#:     requested up to 65536 tokens, but can only afford 14191.
#:
#: It is also just wrong for voice. Three hundred tokens is around a minute of
#: speech, and a spoken answer longer than that is one nobody asked for.
VOICE_REPLY_TOKENS = 300


def reply_tokens(context: int) -> int:
    """How long a spoken reply may be, given what the model can hold.

    Never the whole context. Leaving the cap unset asked for exactly that --
    the plugin sends the model's maximum -- so OpenRouter reserved credit
    against 65,536 tokens and refused every voice turn with a 402.

    The context window now comes from the provider's own model list rather
    than being assumed, and the reply is a small fraction of it: a spoken
    answer is a minute of speech, not a document. A model that reports no
    context simply gets the default.
    """
    if context <= 0:
        return VOICE_REPLY_TOKENS
    # A twentieth, floored at something worth saying and capped where a spoken
    # answer stops being one.
    return max(VOICE_REPLY_TOKENS, min(context // 20, 1024))


def voice_body(config: AgentConfig) -> dict:
    """Extra request fields the voice path needs and was not sending.

    The Gateway asks for both of these on a voice turn. The Agent does not go
    through the Gateway -- it holds the credential and calls the provider
    itself -- so neither was reaching the wire, and the settings existed
    without ever applying to the surface they were written for.

    **Latency routing.** OpenRouter is a gateway: one model name is a family of
    upstreams with different times to first token, and it will pick on price
    unless told otherwise. `sort: latency` is what "voice wants the fastest
    provider" has to look like on the request.

    **Reasoning off.** Thinking happens before the first token, and the first
    token is the entire experience of a spoken turn -- a model that deliberates
    for four seconds has not been thoughtful, it has been silent. Asked off
    explicitly rather than left unset, because several models reason by default
    and silence on the parameter is not the same as "do not".

    Only for OpenRouter: these are its fields, and sending them to an endpoint
    that does not know them is a request some servers reject outright.
    """
    if "openrouter.ai" not in config.base_url.lower():
        return {}
    body: dict = {"reasoning": {"enabled": False, "exclude": True}}
    # Whatever the Gateway was configured with, rather than a policy invented
    # here. This used to hardcode `sort: latency`, which duplicated a setting
    # the user can change and pinned a constraint the numbers do not support:
    # best-case first-token times are the same with it and without, and what
    # actually varies -- by twenty times, run to run -- is which upstream
    # OpenRouter happens to pick.
    if config.route:
        body["provider"] = config.route
    return body


def build_llm(config: AgentConfig) -> openai.LLM:
    """Every provider Marvi speaks to on the voice path is OpenAI-compatible."""
    extra = voice_body(config)
    return openai.LLM(
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
        max_completion_tokens=reply_tokens(config.context),
        **({"extra_body": extra} if extra else {}),
    )


def build_local_turn_detector() -> str:
    """End of turn from VAD silence, decided on this machine.

    It used to return `inference.TurnDetector(version="v1-mini")` under a
    docstring calling it "the local CPU model". It is not: it takes base_url,
    api_key and api_secret, and it asks LiveKit Inference. Marvi runs against a
    self-hosted LiveKit with local keys, so it could never reach it -- and the
    failure was silent in exactly the worst way.

    End of turn never resolved, so the STT stream was never flushed, so no
    FINAL_TRANSCRIPT was ever emitted. Speech was recognised perfectly and
    stayed as interim results forever:

        stt (partial): Hey Morvey, are you listening to me?  Are you here?

    and the model was never called, because as far as the session was
    concerned the user had not stopped speaking.

    "vad" is a first-class mode and it is local. A cloud dependency in the turn
    loop of a local-first assistant was the wrong choice regardless of whether
    it worked.
    """
    return "vad"


def require_selected_voice_adapters(stt: object | None, tts: object | None) -> None:
    if stt is None or tts is None:
        raise VoiceStackPendingError(
            "Native streaming STT/TTS adapters are not selected yet; run the documented bakeoff"
        )
