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

import json
import os
from collections.abc import Callable
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
    #: True for a gateway that fronts several upstream providers per model, so
    #: the request can say which of them to prefer. OpenRouter is the one.
    routes_upstream: bool = False
    supports_tools: bool = True

    cache: CachePolicy = field(default_factory=CachePolicy)
    reasoning: ReasoningPolicy = field(default_factory=ReasoningPolicy)
    limits: LimitPolicy = field(default_factory=LimitPolicy)

    default_model_env: str = ""
    #: Where a persisted reasoning effort is read from. Derived rather than
    #: declared on each provider: the name follows from the provider's own, and
    #: a per-provider literal is one more thing to get wrong for no benefit.
    effort_env: str = ""
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
        # An OAuth provider's credential is a token Marvi obtained and keeps
        # fresh, not something typed into a settings file. The hook is set by
        # `oauth.py` on import; keeping it a hook is what stops this module
        # from knowing anything about OAuth.
        if self.auth_type.startswith("oauth") and _token_hook is not None:
            token = _token_hook(self.name)
            if token:
                return token
        for name in self.key_env:
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return None

    def enabled_setting(self) -> str:
        """Where a local provider records that it was actually connected."""
        return f"MARVI_{self.name.replace('-', '_').upper()}_ENABLED"

    def configured(self) -> bool:
        """Reachable and chosen, not merely present.

        A local provider used to count as configured because it had a default
        base URL -- which every one of them ships with. So LM Studio and Ollama
        were permanently "connected" on a machine where neither was running,
        won the fallback ordering, and answered turns with nothing behind them.
        That is how a voice session ended up resolved to "LM Studio /" with no
        model at all.

        They need connecting now, like everything else: pressing Connect probes
        the endpoint, and only a real model list writes the flag this reads.
        """
        if not self.base_url():
            return False
        if self.auth_type == "none":
            raw = os.environ.get(self.enabled_setting(), "").strip().lower()
            return raw in ("1", "true", "yes", "on")
        try:
            return bool(self.api_key())
        except Exception:
            # An expired OAuth session is "connected but broken", which the
            # page reports separately. It is not configured for calling.
            return False

    def effort_for(self) -> str | None:
        """The configured reasoning effort, if this provider takes one.

        Applied to every call rather than only where a caller thought to pass
        one: effort was a parameter nothing set, so a provider's reasoning
        settings were unreachable from the UI and every call ran at whatever
        the provider's own default happened to be.
        """
        if self.reasoning.style != "effort":
            return None
        name = self.effort_env or f"MARVI_{self.name.replace('-', '_').upper()}_EFFORT"
        return self.reasoning.normalise(os.environ.get(name, "").strip() or None)

    def effort_setting(self) -> str:
        """The environment variable the UI writes an effort choice to."""
        if self.reasoning.style != "effort":
            return ""
        return self.effort_env or f"MARVI_{self.name.replace('-', '_').upper()}_EFFORT"

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
        tools: list[dict[str, Any]] | None = None,
        job: str = "main",
    ) -> dict[str, Any]:
        """Assemble a request body in this provider's own wire format.

        `tools` is given in the neutral shape `{name, description, parameters}`
        and translated per provider — the three formats disagree about where
        the schema goes, which is the same reason `build_request` exists at all.
        """
        chosen = model or self.model_for()
        limit = max_tokens or self.default_max_tokens
        wants_stream = stream and self.supports_streaming
        # Voice never reasons. Thinking happens before the first token, and the
        # first token is the entire experience of a spoken turn: a model that
        # deliberates for four seconds has not been thoughtful, it has been
        # silent. Enforced here rather than at each call site, because a rule
        # every caller has to remember is a rule that gets forgotten.
        if job == "voice":
            effort = None

        if self.api_mode == "anthropic":
            system, chat = _split_system(messages)
            chat = _as_anthropic(chat)
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
            elif job == "voice" and self.reasoning.style == "budget_tokens":
                body["thinking"] = {"type": "disabled"}
            if tools and self.supports_tools:
                body["tools"] = [
                    {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "input_schema": t.get("parameters", {}),
                    }
                    for t in tools
                ]
            return body

        if self.api_mode == "responses":
            body = {"model": chosen, "input": _as_responses(messages)}
            if limit:
                body["max_output_tokens"] = limit
            if wants_stream:
                body["stream"] = True
            normalised = self.reasoning.normalise(effort)
            if normalised:
                body["reasoning"] = {"effort": normalised}
            if cache_prefix and self.cache.style == "cache_key":
                body["prompt_cache_key"] = "marvi-system"
            if tools and self.supports_tools:
                body["tools"] = [
                    {
                        "type": "function",
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {}),
                    }
                    for t in tools
                ]
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
        elif job == "voice" and self.reasoning.style != "none":
            # Asked off rather than merely left unset: several models reason by
            # default, and silence on the parameter is not the same as "do not".
            body["reasoning"] = {"enabled": False, "exclude": True}
        if cache_prefix and self.cache.style == "cache_key":
            body["prompt_cache_key"] = "marvi-system"
        if self.routes_upstream:
            # OpenRouter is a gateway: the model names a family of upstream
            # providers with different prices and different times to first
            # token, and choosing between them is a decision voice cares about.
            from .openrouter import route_for

            route = route_for(job).as_body()
            if route:
                body["provider"] = route
        if tools and self.supports_tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {}),
                    },
                }
                for t in tools
            ]
        return body

    # -- response reading ----------------------------------------------------

    def read_tool_calls(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Tool calls the model asked for, normalised to {id, name, arguments}.

        Returned rather than executed: nothing in this module is allowed to run
        a tool. The caller routes them through the confirmation flow, which is
        the only path that exists.
        """
        import json as _json

        def parse(raw: Any) -> dict[str, Any]:
            if isinstance(raw, dict):
                return raw
            try:
                loaded = _json.loads(raw or "{}")
            except (TypeError, ValueError):
                return {}
            return loaded if isinstance(loaded, dict) else {}

        if self.api_mode == "anthropic":
            return [
                {"id": block.get("id", ""), "name": block.get("name", ""),
                 "arguments": parse(block.get("input"))}
                for block in payload.get("content", []) or []
                if block.get("type") == "tool_use"
            ]

        if self.api_mode == "responses":
            return [
                {"id": item.get("call_id") or item.get("id", ""), "name": item.get("name", ""),
                 "arguments": parse(item.get("arguments"))}
                for item in payload.get("output", []) or []
                if item.get("type") == "function_call"
            ]

        choices = payload.get("choices") or []
        if not choices:
            return []
        message = choices[0].get("message") or {}
        return [
            {"id": call.get("id", ""), "name": (call.get("function") or {}).get("name", ""),
             "arguments": parse((call.get("function") or {}).get("arguments"))}
            for call in message.get("tool_calls") or []
        ]

    def read_stream_line(self, line: str) -> dict[str, Any] | None:
        """One line of a streaming response, as a delta or a usage report.

        Three API modes, three envelopes, and all three arrive as
        Server-Sent Events: a `data: ` prefix, JSON after it, and a `[DONE]`
        sentinel from the OpenAI-shaped ones. Returns None for anything with
        nothing in it — keep-alives, blank lines, the sentinel — so the caller
        can filter without knowing any of that.
        """
        text = (line or "").strip()
        if not text or not text.startswith("data:"):
            return None
        payload = text[5:].strip()
        if not payload or payload == "[DONE]":
            return None
        try:
            chunk = json.loads(payload)
        except ValueError:
            return None

        if self.api_mode == "anthropic":
            # Anthropic names the event and puts the text one level deeper.
            kind = chunk.get("type", "")
            if kind == "content_block_delta":
                block = chunk.get("delta") or {}
                # Thinking arrives interleaved with the answer and must never
                # be spoken or shown as the reply.
                if block.get("type") == "thinking_delta":
                    thought = block.get("thinking", "")
                    return {"reasoning": thought} if thought else None
                delta = block.get("text", "")
                return {"delta": delta} if delta else None
            if kind in ("message_delta", "message_stop"):
                usage = chunk.get("usage") or (chunk.get("message") or {}).get("usage")
                return {"usage": {"usage": usage}} if usage else None
            return None

        if self.api_mode == "responses":
            kind = chunk.get("type", "")
            if kind == "response.output_text.delta":
                delta = chunk.get("delta", "")
                return {"delta": delta} if delta else None
            if kind in (
                "response.reasoning_text.delta",
                "response.reasoning_summary_text.delta",
            ):
                thought = chunk.get("delta", "")
                return {"reasoning": thought} if thought else None
            if kind == "response.completed":
                usage = (chunk.get("response") or {}).get("usage")
                return {"usage": {"usage": usage}} if usage else None
            return None

        # chat_completions
        choices = chunk.get("choices") or []
        if choices:
            delta = choices[0].get("delta") or {}
            text = delta.get("content") or ""
            if text:
                return {"delta": text}

            # Reasoning, in the three shapes the OpenAI-compatible world uses.
            # OpenRouter documents `reasoning_details` -- a list of typed parts
            # -- and also sends a plain `reasoning` string; DeepSeek calls it
            # `reasoning_content`. Checked against OpenRouter's own reasoning
            # docs rather than guessed.
            details = delta.get("reasoning_details") or []
            if details:
                thought = "".join(
                    str(part.get("text") or "")
                    for part in details
                    if isinstance(part, dict) and "text" in part
                )
                if thought:
                    return {"reasoning": thought}
            thought = delta.get("reasoning") or delta.get("reasoning_content") or ""
            if thought:
                return {"reasoning": str(thought)}

            # Tool calls arrive in fragments: an index, and a name or a slice
            # of the argument JSON. Passed through whole for the caller to
            # reassemble, because only it knows when the round is over.
            calls = delta.get("tool_calls")
            if calls:
                return {"tool_calls": calls}
        # OpenAI sends usage in a final chunk when asked to; it has no choices.
        if chunk.get("usage"):
            return {"usage": {"usage": chunk["usage"]}}
        return None

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
        # DeepSeek publishes no prompt_tokens_details; it splits input into hit
        # and miss counters instead. Reading only the OpenAI shape would bill
        # every cached token as fresh on the provider that caches hardest.
        cached = int(
            details.get("cached_tokens", raw.get("prompt_cache_hit_tokens", 0)) or 0
        )
        return Usage(
            input=int(raw.get("prompt_tokens", raw.get("input_tokens", 0)) or 0),
            output=int(raw.get("completion_tokens", raw.get("output_tokens", 0)) or 0),
            cached_input=cached,
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


def _tool_calls_of(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = message.get("tool_calls")
    return calls if isinstance(calls, list) else []


def _arguments_of(call: dict[str, Any]) -> dict[str, Any]:
    """A call's arguments as an object.

    On the wire they are a JSON string, because that is how models emit them
    incrementally. Anthropic and the Responses API want them parsed.
    """
    import json as _json

    raw = (call.get("function") or {}).get("arguments")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = _json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _as_anthropic(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same round trip, in Anthropic's content blocks.

    A call is a `tool_use` block on the assistant turn; a result is a
    `tool_result` block on a user turn, naming the id it answers.
    """
    out: list[dict[str, Any]] = []
    for message in messages:
        calls = _tool_calls_of(message)
        if calls:
            out.append(
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": call.get("id") or "",
                            "name": (call.get("function") or {}).get("name") or "",
                            "input": _arguments_of(call),
                        }
                        for call in calls
                    ],
                }
            )
            continue
        if message.get("role") == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.get("tool_call_id") or "",
                            "content": str(message.get("content") or ""),
                        }
                    ],
                }
            )
            continue
        out.append(message)
    return out


def _as_responses(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same round trip, as Responses API items.

    A call is a `function_call` item and a result a `function_call_output`,
    both keyed by `call_id` rather than by message order.
    """
    import json as _json

    out: list[dict[str, Any]] = []
    for message in messages:
        calls = _tool_calls_of(message)
        if calls:
            for call in calls:
                out.append(
                    {
                        "type": "function_call",
                        "call_id": call.get("id") or "",
                        "name": (call.get("function") or {}).get("name") or "",
                        "arguments": _json.dumps(_arguments_of(call)),
                    }
                )
            continue
        if message.get("role") == "tool":
            out.append(
                {
                    "type": "function_call_output",
                    "call_id": message.get("tool_call_id") or "",
                    "output": str(message.get("content") or ""),
                }
            )
            continue
        out.append(message)
    return out


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


# Set by `oauth.py` when it is imported, so `api_key()` can resolve a live
# access token without `base` importing the OAuth machinery.
_token_hook: Callable[[str], str | None] | None = None


def set_token_hook(hook: Callable[[str], str | None] | None) -> None:
    global _token_hook
    _token_hook = hook


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
