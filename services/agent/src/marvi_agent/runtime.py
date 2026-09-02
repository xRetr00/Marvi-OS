"""What the voice worker needs before it can speak.

No provider is named here. The Agent runs in its own Python environment and
must not carry a second copy of the provider table — two copies drift, and the
one that drifts is always the one the user did not edit.

Instead it asks the Gateway, over the same loopback channel it already uses for
tools, and gets back whatever the user configured in the control center. The
registry in `marvi_gateway.providers` stays the single source of truth.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

import httpx
from livekit.plugins import openai

log = logging.getLogger("marvi.voice")

RESOLVE_TIMEOUT = 8.0

#: How many times to ask the Gateway for the voice model before giving up, and
#: how long to wait between. See `AgentConfig.from_gateway`: a busy Gateway is
#: not a missing one, and the difference decides whether voice starts.
ATTEMPTS = 3
RETRY_PAUSE = 1.5


class VoiceStackPendingError(RuntimeError):
    """Raised until the native-Windows STT/TTS bakeoff selects both adapters."""


class ProviderUnavailableError(RuntimeError):
    """The Gateway could not name a usable provider for the voice path."""


def gateway_base_url() -> str:
    return os.environ.get("MARVI_GATEWAY_URL", "http://127.0.0.1:8765").rstrip("/")


#: The per-launch secret the desktop puts in every child's environment. See
#: `marvi_gateway.localauth`: `/providers/voice` answers with the provider's
#: raw API key, and it used to answer to anyone who could reach loopback.
LOCAL_TOKEN = "MARVI_LOCAL_TOKEN"


def local_token_header() -> dict[str, str]:
    """The header that proves this process was started alongside the Gateway."""
    token = os.environ.get(LOCAL_TOKEN, "").strip()
    return {"x-marvi-local": token} if token else {}


@dataclass(frozen=True, slots=True)
class AgentConfig:
    api_key: str
    model: str
    base_url: str
    provider: str = "unknown"
    #: Provider-documented app metadata. The Gateway remains the source of
    #: truth because the Agent must not carry a second provider table.
    headers: dict[str, str] = field(default_factory=dict)
    #: The model's context window, as the provider reports it. Zero when it
    #: does not, in which case the reply cap stands on its own.
    context: int = 0
    #: Upstream routing, as configured. Empty for a provider that has none.
    route: dict = field(default_factory=dict)

    @classmethod
    def from_gateway(cls, client: httpx.Client | None = None) -> AgentConfig:
        """The voice model, asked for once per session.

        Retried, because this is the first thing a session does and the only
        thing that can stop it starting at all. Twice in one evening a run died
        here while the Gateway was up and answering `/health` -- it was busy
        with a connector's network calls and the eight-second read expired,
        which reached the user as "No provider is configured. Connect one in
        the Marvi control center." Voice failed to start, and the message
        pointed at a setting that was correct.

        A retry is the right shape rather than a longer timeout: what is being
        waited on is another local process finishing something, and it either
        frees up in a moment or is genuinely gone.
        """
        for attempt in range(ATTEMPTS):
            try:
                return cls._ask(client)
            except ProviderUnavailableError:
                # A Gateway that answers "no provider" has answered. Retrying
                # asks a question that has already been settled.
                raise
            except httpx.HTTPStatusError as exc:
                # A 403 here is `localauth` refusing this process, and no
                # number of retries fixes it. It was logged as "the Gateway did
                # not answer in time", which is what a timeout looks like and
                # sent the search in the wrong direction -- the log has 285 of
                # these and a job that died with an unhandled exception four
                # seconds later.
                if exc.response.status_code == 403:
                    raise ProviderUnavailableError(
                        "The Gateway refused this process its provider "
                        "credentials (403). MARVI_LOCAL_TOKEN does not match "
                        "the one the Gateway was started with -- usually a "
                        "Gateway left running from an earlier launch. Restart "
                        "Marvi so both are started together. See "
                        "marvi_gateway/localauth.py."
                    ) from exc
                if attempt == ATTEMPTS - 1:
                    raise ProviderUnavailableError(
                        f"Marvi Gateway is unreachable: {exc}"
                    ) from exc
                log.info("the Gateway answered %s; asking again", exc)
            except httpx.HTTPError as exc:
                if attempt == ATTEMPTS - 1:
                    raise ProviderUnavailableError(
                        f"Marvi Gateway is unreachable: {exc}"
                    ) from exc
                log.info("the Gateway did not answer in time (%s); asking again", exc)
                time.sleep(RETRY_PAUSE)
        raise ProviderUnavailableError("Marvi Gateway is unreachable")

    @classmethod
    def _ask(cls, client: httpx.Client | None = None) -> AgentConfig:
        http = client or httpx.Client(timeout=RESOLVE_TIMEOUT)
        try:
            # The Gateway will not hand a credential to an unauthenticated
            # caller any more. Both processes are started by the same
            # supervisor with the same environment, which is what makes this
            # the Agent and not a browser tab on the same loopback. Absent
            # outside the app, where the Gateway does not require it either.
            response = http.get(
                f"{gateway_base_url()}/providers/voice", headers=local_token_header()
            )
            if response.status_code == 503:
                raise ProviderUnavailableError(
                    "No provider is configured. Connect one in the Marvi control center."
                )
            response.raise_for_status()
            body = response.json()
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
            headers=body.get("headers") or {},
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
#: The backstop on a spoken reply. Roughly 190 words, or about a minute --
#: long enough for a genuine explanation and short enough that a model that has
#: started drifting is cut off rather than narrated. The prompt asks for one or
#: two sentences; this is what happens when it is not obeyed.
VOICE_REPLY_TOKENS = 250


def reply_tokens(context: int) -> int:
    """How long a spoken reply may be.

    Never the whole context. Leaving the cap unset asked for exactly that --
    the plugin sends the model's maximum -- so OpenRouter reserved credit
    against 65,536 tokens and refused every voice turn with a 402.

    **It does not scale with the context window any more.** It used to be a
    twentieth of it, capped at 1024, which on a 128k model meant 1024 tokens --
    roughly 770 words, or **five minutes** of continuous speech. A real
    conversation produced a single reply of 48 seconds. The comment above that
    line said "capped where a spoken answer stops being one", and 1024 tokens
    is nowhere near it.

    The mistake was the shape rather than the number: how long somebody wants
    to be spoken at has nothing to do with how much the model can hold. A
    spoken answer is a few sentences, and this is the backstop for when the
    prompt asking for a few sentences does not land.

    `context` still matters in one direction: a model too small to hold both
    the conversation and the reply should not be asked to reserve the whole
    window for the reply. It never raises the cap, only lowers it.
    """
    if 0 < context < VOICE_REPLY_TOKENS * 8:
        return max(64, context // 8)
    return VOICE_REPLY_TOKENS


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

    Measured on the model that ships, one sentence, three ways:

        default (nothing asked)      4.25s   completion 528, reasoning 356
        enabled:false exclude:true   1.64s   completion 168, reasoning 0
        enabled:false                1.48s   completion 161, reasoning 0

    Nearly three seconds of silence, bought back by one field. Off is not an
    optimisation here, it is the difference between a conversation and a wait.

    Every provider, not only OpenRouter, and that is a fix rather than a
    tidy-up: the guard below used to return `{}` for anything else, so
    changing provider silently turned thinking back on and the voice path
    became slow again with nothing to say why. Each dialect is spelled the way
    that provider spells it -- there is no shared field -- and an endpoint that
    does not know a field is the reason this is a lookup and not a union.
    """
    where = config.base_url.lower()
    if "openrouter.ai" in where:
        body: dict = {"reasoning": {"enabled": False, "exclude": True}}
    elif "localhost" in where or "127.0.0.1" in where:
        # Ollama and vLLM both take the template flag; it is what turns off
        # Qwen3's `<think>` block at the template level rather than asking the
        # model nicely in the prompt.
        return {"chat_template_kwargs": {"enable_thinking": False}}
    else:
        # OpenAI's own spelling, which the OpenAI-compatible endpoints that
        # have a knob at all have settled on. Providers without one ignore it.
        return {"reasoning_effort": "none"}
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
        **({"extra_headers": config.headers} if config.headers else {}),
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
