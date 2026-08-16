"""Provider profiles: the single source of truth for how to reach a model.

Every provider is one module in this package. Nothing about a provider — no
base URL, no model name, no key — appears anywhere else in the codebase, and
everything resolves from environment or config so it stays editable from the
control center.

The reason this is a real abstraction rather than "a URL and a key" is that
providers differ in four ways that change the request itself:

* **API shape.** OpenAI chat completions, OpenAI Responses, and Anthropic
  Messages are three different wire formats, not three URLs.
* **Streaming.** The voice path needs tokens as they arrive; background
  deliberation does not and should not pay the complexity.
* **Reasoning effort.** Some models take an effort level, some take a thinking
  token budget, most take neither, and sending the wrong one is an error.
* **Prompt caching.** This is the cost lever. A cached input token is a
  fraction of the price of a fresh one, and since Marvi's budget is denominated
  in tokens (see `docs/phases/09-providers-identity.md`), caching is what makes
  a long-lived system prompt affordable. Providers disagree on how to ask for
  it, so the profile carries the style and the caller never guesses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any, Literal

ApiMode = Literal["chat_completions", "responses", "anthropic"]
AccessPath = Literal["api", "plan", "local"]
AuthType = Literal["api_key", "oauth_external", "oauth_device_code", "token_exchange", "none"]
CacheStyle = Literal["none", "automatic", "cache_key", "explicit_breakpoints"]
ReasoningStyle = Literal["none", "effort", "budget_tokens"]
LimitStyle = Literal["none", "credit", "rolling_windows"]


class ProviderError(Exception):
    pass


class ProviderNotConfiguredError(ProviderError):
    """The provider exists but has no credentials or endpoint."""


@dataclass(frozen=True)
class CachePolicy:
    """How to ask this provider to reuse a prompt prefix.

    Caching is the cheapest optimisation available: the system prompt, identity
    files, and tool schemas are identical on every turn, so paying full price
    for them every time is pure waste.
    """

    style: CacheStyle = "none"
    # Below this, providers typically refuse to cache and the request is
    # unchanged. Sending breakpoints for a tiny prompt just adds noise.
    min_tokens: int = 1024
    # Anthropic-style: how many explicit breakpoints the API allows.
    max_breakpoints: int = 4

    @property
    def caches(self) -> bool:
        return self.style != "none"


@dataclass(frozen=True)
class ReasoningPolicy:
    style: ReasoningStyle = "none"
    levels: tuple[str, ...] = ()
    default: str = ""

    def normalise(self, effort: str | None) -> str | None:
        """Return an effort this provider will actually accept, or None."""
        if self.style != "effort" or not effort:
            return None
        return effort if effort in self.levels else (self.default or None)


@dataclass(frozen=True)
class LimitPolicy:
    """What the provider meters, for display only.

    Budget *control* is always token-based; see the phase document. This exists
    so the UI can show credit or a rolling window where the provider publishes
    one, and say plainly when it does not.
    """

    style: LimitStyle = "none"
    # Rolling windows as (label, hours) — Go is $12/5h, $30/week, $60/month.
    windows: tuple[tuple[str, int], ...] = ()
    # True when usage can be read back from the API rather than only a console.
    readable: bool = False
    note: str = ""


@dataclass(frozen=True)
class Usage:
    """Token accounting, cache-aware.

    `cached_input` is separated because it is the whole point of caching: the
    budget should see that a 4,000-token system prompt cost almost nothing on
    its second use.
    """

    input: int = 0
    output: int = 0
    cached_input: int = 0
    reasoning: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output

    @property
    def billable(self) -> int:
        """Fresh input plus output. Cached input is excluded deliberately —
        it is charged at a small fraction and treating it as free keeps the
        budget honest about what caching actually saves."""
        return max(0, self.input - self.cached_input) + self.output

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input=self.input + other.input,
            output=self.output + other.output,
            cached_input=self.cached_input + other.cached_input,
            reasoning=self.reasoning + other.reasoning,
        )


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    access_path: AccessPath = "api"
    auth_type: AuthType = "api_key"
    api_mode: ApiMode = "chat_completions"

    aliases: tuple[str, ...] = ()
    display_name: str = ""
    description: str = ""
    signup_url: str = ""

    # Resolved from the environment, never literal at a call site.
    base_url_env: str = ""
    default_base_url: str = ""
    key_env: tuple[str, ...] = ()
    models_path: str = "/models"

    supports_streaming: bool = True
    supports_vision: bool = False
    supports_tools: bool = True

    cache: CachePolicy = field(default_factory=CachePolicy)
    reasoning: ReasoningPolicy = field(default_factory=ReasoningPolicy)
    limits: LimitPolicy = field(default_factory=LimitPolicy)

    default_model_env: str = ""
    default_model: str = ""
    default_aux_model: str = ""
    default_vision_model: str = ""
    fallback_models: tuple[str, ...] = ()

    default_headers: dict[str, str] = field(default_factory=dict)
    default_max_tokens: int | None = None

    # -- resolution ----------------------------------------------------------

    def base_url(self) -> str:
        if self.base_url_env:
            configured = os.environ.get(self.base_url_env, "").strip()
            if configured:
                return configured.rstrip("/")
        return self.default_base_url.rstrip("/")

    def api_key(self) -> str | None:
        for name in self.key_env:
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return None

    def configured(self) -> bool:
        """Local providers need only an endpoint; the rest need a credential."""
        if not self.base_url():
            return False
        return True if self.auth_type == "none" else bool(self.api_key())

    def model_for(self, job: Literal["main", "aux", "vision"] = "main") -> str:
        if job == "aux" and self.default_aux_model:
            return self.default_aux_model
        if job == "vision":
            return self.default_vision_model or self.default_model
        if self.default_model_env:
            configured = os.environ.get(self.default_model_env, "").strip()
            if configured:
                return configured
        return self.default_model

    def label(self) -> str:
        return self.display_name or self.name

    def with_overrides(self, **changes: Any) -> ProviderProfile:
        return replace(self, **changes)

    # -- request shaping -----------------------------------------------------

    def headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json", **self.default_headers}
        key = self.api_key()
        if not key:
            return headers
        if self.api_mode == "anthropic":
            headers["x-api-key"] = key
            headers.setdefault("anthropic-version", "2023-06-01")
        else:
            headers["authorization"] = f"Bearer {key}"
        return headers

    def endpoint(self) -> str:
        base = self.base_url()
        if self.api_mode == "responses":
            return f"{base}/responses"
        if self.api_mode == "anthropic":
            return f"{base}/v1/messages"
        return f"{base}/chat/completions"

    def build_request(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        effort: str | None = None,
        cache_prefix: bool = False,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Assemble a request body in this provider's own wire format."""
        chosen = model or self.model_for()
        limit = max_tokens or self.default_max_tokens
        wants_stream = stream and self.supports_streaming

        if self.api_mode == "anthropic":
            system, chat = _split_system(messages)
            body: dict[str, Any] = {"model": chosen, "messages": chat}
            if system:
                # Anthropic marks cache breakpoints on content blocks, so the
                # system prompt becomes a block that can carry cache_control.
                block: dict[str, Any] = {"type": "text", "text": system}
                if cache_prefix and self.cache.style == "explicit_breakpoints":
                    block["cache_control"] = {"type": "ephemeral"}
                body["system"] = [block]
            body["max_tokens"] = limit or 1024
            if wants_stream:
                body["stream"] = True
            if temperature is not None:
                body["temperature"] = temperature
            if self.reasoning.style == "budget_tokens" and effort:
                body["thinking"] = {"type": "enabled", "budget_tokens": int(effort)}
            return body

        if self.api_mode == "responses":
            body = {"model": chosen, "input": messages}
            if limit:
                body["max_output_tokens"] = limit
            if wants_stream:
                body["stream"] = True
            normalised = self.reasoning.normalise(effort)
            if normalised:
                body["reasoning"] = {"effort": normalised}
            if cache_prefix and self.cache.style == "cache_key":
                body["prompt_cache_key"] = "marvi-system"
            return body

        body = {"model": chosen, "messages": messages}
        if limit:
            body["max_tokens"] = limit
        if wants_stream:
            body["stream"] = True
            # Without this many OpenAI-compatible servers omit usage entirely
            # on streamed responses, and the token budget goes blind.
            body["stream_options"] = {"include_usage": True}
        if temperature is not None:
            body["temperature"] = temperature
        normalised = self.reasoning.normalise(effort)
        if normalised:
            body["reasoning_effort"] = normalised
        if cache_prefix and self.cache.style == "cache_key":
            body["prompt_cache_key"] = "marvi-system"
        return body

    # -- response reading ----------------------------------------------------

    def read_usage(self, payload: dict[str, Any]) -> Usage:
        """Pull token counts out of this provider's response shape."""
        raw = payload.get("usage") or {}
        if self.api_mode == "anthropic":
            cached = int(raw.get("cache_read_input_tokens", 0) or 0)
            return Usage(
                input=int(raw.get("input_tokens", 0) or 0) + cached,
                output=int(raw.get("output_tokens", 0) or 0),
                cached_input=cached,
            )
        details = raw.get("prompt_tokens_details") or {}
        completion_details = raw.get("completion_tokens_details") or {}
        return Usage(
            input=int(raw.get("prompt_tokens", raw.get("input_tokens", 0)) or 0),
            output=int(raw.get("completion_tokens", raw.get("output_tokens", 0)) or 0),
            cached_input=int(details.get("cached_tokens", 0) or 0),
            reasoning=int(completion_details.get("reasoning_tokens", 0) or 0),
        )

    def read_text(self, payload: dict[str, Any]) -> str:
        if self.api_mode == "anthropic":
            parts = [b.get("text", "") for b in payload.get("content", []) or []]
            return "".join(parts)
        if self.api_mode == "responses":
            if isinstance(payload.get("output_text"), str):
                return payload["output_text"]
            chunks: list[str] = []
            for item in payload.get("output", []) or []:
                for block in item.get("content", []) or []:
                    if isinstance(block.get("text"), str):
                        chunks.append(block["text"])
            return "".join(chunks)
        choices = payload.get("choices") or []
        if not choices:
            return ""
        return (choices[0].get("message") or {}).get("content") or ""


def _split_system(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Anthropic takes the system prompt beside the messages, not inside them."""
    system = " ".join(
        str(m.get("content", "")) for m in messages if m.get("role") == "system"
    ).strip()
    return system, [m for m in messages if m.get("role") != "system"]


# -- registry ----------------------------------------------------------------

_REGISTRY: dict[str, ProviderProfile] = {}
_ALIASES: dict[str, str] = {}


def register(profile: ProviderProfile) -> ProviderProfile:
    _REGISTRY[profile.name] = profile
    for alias in profile.aliases:
        _ALIASES[alias] = profile.name
    return profile


def get(name: str) -> ProviderProfile:
    key = (name or "").strip().lower()
    resolved = _ALIASES.get(key, key)
    if resolved not in _REGISTRY:
        raise ProviderError(f"unknown provider: {name}")
    return _REGISTRY[resolved]


def all_profiles() -> list[ProviderProfile]:
    return sorted(_REGISTRY.values(), key=lambda p: (p.access_path, p.name))


def configured_profiles() -> list[ProviderProfile]:
    return [p for p in all_profiles() if p.configured()]


def select(preferred: str | None = None) -> ProviderProfile:
    """Pick a provider: the requested one, else MARVI_PROVIDER, else whichever
    configured provider comes first with local preferred — a local endpoint
    costs nothing and works offline, so it is the safest default."""
    if preferred:
        return get(preferred)
    requested = os.environ.get("MARVI_PROVIDER", "").strip()
    if requested:
        return get(requested)
    ready = configured_profiles()
    if not ready:
        raise ProviderNotConfiguredError(
            "No provider is configured. Set MARVI_PROVIDER and its credentials."
        )
    ready.sort(key=lambda p: 0 if p.access_path == "local" else 1)
    return ready[0]
