"""OpenRouter, DeepInfra, and DeepSeek — three metered, OpenAI-compatible APIs.

These need no new machinery. The client, accounting, cooldown, and failover
already exist, so a provider is now genuinely just a profile. That is the payoff
from building the client before the fourth, fifth and sixth provider rather than
after.

Two of them are worth a note:

* **OpenRouter is the only provider Marvi can read a balance from.** `GET
  /credits` returns what has been granted and used, so the page can show a real
  number instead of "check your dashboard".
* **DeepSeek reports its cache differently.** It has no `prompt_tokens_details`;
  it splits input into `prompt_cache_hit_tokens` and `prompt_cache_miss_tokens`.
  Reading only the OpenAI shape would count every cached token as fresh and the
  budget would over-charge on the provider whose caching is most aggressive —
  handled in `read_usage`.
"""

from __future__ import annotations

from .base import (
    MARVI_APP_NAME,
    MARVI_APP_URL,
    CachePolicy,
    LimitPolicy,
    ProviderProfile,
    ReasoningPolicy,
    register,
)

openrouter = register(
    ProviderProfile(
        name="openrouter",
        aliases=("or",),
        display_name="OpenRouter",
        description="One key across many vendors, billed from a shared credit balance.",
        signup_url="https://openrouter.ai/keys",
        access_path="api",
        auth_type="api_key",
        api_mode="chat_completions",
        base_url_env="MARVI_OPENROUTER_URL",
        default_base_url="https://openrouter.ai/api/v1",
        key_env=("OPENROUTER_API_KEY",),
        default_model_env="MARVI_OPENROUTER_MODEL",
        default_model="anthropic/claude-sonnet-5",
        # Checked against the live catalog rather than guessed. The previous
        # value, `google/gemini-3-flash`, has never existed -- OpenRouter
        # answers "not a valid model ID" with a 400, so every auxiliary call
        # failed: memory extraction, skill proposals, dreaming, titles, the
        # background mind. Nothing said so, because every one of them treats
        # "no answer" as a normal outcome and carries on.
        default_aux_model="google/gemini-3.5-flash-lite",
        default_vision_model="anthropic/claude-sonnet-5",
        supports_vision=True,
        routes_upstream=True,
        # OpenRouter uses these two headers to associate usage with the public
        # app. `X-OpenRouter-Title` is the current spelling; `X-Title` remains
        # only as a backward-compatible alias in their API.
        default_headers={
            "HTTP-Referer": MARVI_APP_URL,
            "X-OpenRouter-Title": MARVI_APP_NAME,
        },
        # OpenRouter forwards `prompt_cache_key` to backends that support it and
        # ignores it elsewhere, so sending it is free.
        cache=CachePolicy(style="cache_key", min_tokens=1024),
        reasoning=ReasoningPolicy(
            style="effort",
            levels=("none", "minimal", "low", "medium", "high", "xhigh", "max"),
        ),
        limits=LimitPolicy(
            style="credit",
            readable=True,
            note="Per-key spend and limits are readable from /api/v1/key.",
        ),
        default_max_tokens=4096,
    )
)

deepinfra = register(
    ProviderProfile(
        name="deepinfra",
        display_name="DeepInfra",
        description="Open-weight models served per token.",
        signup_url="https://deepinfra.com/dash/api_keys",
        access_path="api",
        auth_type="api_key",
        api_mode="chat_completions",
        base_url_env="MARVI_DEEPINFRA_URL",
        default_base_url="https://api.deepinfra.com/v1/openai",
        key_env=("DEEPINFRA_API_KEY",),
        default_model_env="MARVI_DEEPINFRA_MODEL",
        default_model="deepseek-ai/DeepSeek-V3.2",
        default_aux_model="Qwen/Qwen3-8B",
        # No prompt-cache control on the wire; the servers keep their own.
        cache=CachePolicy(style="none"),
        reasoning=ReasoningPolicy(style="effort", levels=("none", "low", "medium", "high")),
        limits=LimitPolicy(
            style="credit",
            readable=True,
            note="Monthly account cost is readable from /payment/usage.",
        ),
        default_max_tokens=4096,
    )
)

deepseek = register(
    ProviderProfile(
        name="deepseek",
        display_name="DeepSeek",
        description="DeepSeek's own API, with automatic disk-based prompt caching.",
        signup_url="https://platform.deepseek.com/api_keys",
        access_path="api",
        auth_type="api_key",
        api_mode="chat_completions",
        base_url_env="MARVI_DEEPSEEK_URL",
        default_base_url="https://api.deepseek.com",
        key_env=("DEEPSEEK_API_KEY",),
        default_model_env="MARVI_DEEPSEEK_MODEL",
        default_model="deepseek-chat",
        default_aux_model="deepseek-chat",
        # Caching is on by the provider's own choice with nothing to send; the
        # saving still shows up in usage, which is what the budget reads.
        cache=CachePolicy(style="automatic"),
        reasoning=ReasoningPolicy(style="effort", levels=("none", "low", "high", "max")),
        limits=LimitPolicy(
            style="credit",
            readable=True,
            note="Account balance is readable from /user/balance.",
        ),
        default_max_tokens=4096,
    )
)
