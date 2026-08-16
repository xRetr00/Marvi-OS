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

from .base import CachePolicy, LimitPolicy, ProviderProfile, ReasoningPolicy, register

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
        default_aux_model="google/gemini-3-flash",
        default_vision_model="anthropic/claude-sonnet-5",
        supports_vision=True,
        # OpenRouter forwards `prompt_cache_key` to backends that support it and
        # ignores it elsewhere, so sending it is free.
        cache=CachePolicy(style="cache_key", min_tokens=1024),
        reasoning=ReasoningPolicy(
            style="effort", levels=("low", "medium", "high"), default="low"
        ),
        limits=LimitPolicy(
            style="credit",
            readable=True,
            note="Credit balance is readable from /credits.",
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
        reasoning=ReasoningPolicy(style="none"),
        limits=LimitPolicy(
            style="credit",
            readable=False,
            note="Balance and spend are shown in the DeepInfra dashboard.",
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
        reasoning=ReasoningPolicy(style="none"),
        limits=LimitPolicy(
            style="credit",
            readable=False,
            note="Balance is shown in the DeepSeek platform console.",
        ),
        default_max_tokens=4096,
    )
)
