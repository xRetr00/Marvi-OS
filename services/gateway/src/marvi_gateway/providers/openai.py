"""OpenAI, and the Codex plan.

Two profiles, one vendor. The API is metered per token against a key; Codex is
reached through a ChatGPT subscription over OAuth and speaks the Responses API.

Caching differs from Anthropic's in an important way: OpenAI caches prompt
prefixes automatically above a minimum length, and `prompt_cache_key` only
improves routing so the same prefix lands on the same backend. There is nothing
to mark, so a long stable system prompt is cached whether or not Marvi asks —
but sending the key makes the hit rate far more reliable.
"""

from __future__ import annotations

from .base import CachePolicy, LimitPolicy, ProviderProfile, ReasoningPolicy, register

openai_api = register(
    ProviderProfile(
        name="openai",
        aliases=("gpt", "openai-api"),
        display_name="OpenAI",
        description="OpenAI's metered API, billed per token.",
        signup_url="https://platform.openai.com/api-keys",
        access_path="api",
        auth_type="api_key",
        # Chat completions remains the broadest surface; Responses is selected
        # per-profile below for the reasoning path.
        api_mode="chat_completions",
        base_url_env="MARVI_OPENAI_URL",
        default_base_url="https://api.openai.com/v1",
        key_env=("OPENAI_API_KEY",),
        default_model_env="MARVI_OPENAI_MODEL",
        default_model="gpt-5.2",
        default_aux_model="gpt-5.2-mini",
        default_vision_model="gpt-5.2",
        supports_vision=True,
        cache=CachePolicy(style="cache_key", min_tokens=1024),
        reasoning=ReasoningPolicy(
            style="effort", levels=("minimal", "low", "medium", "high"), default="low"
        ),
        limits=LimitPolicy(
            style="credit",
            readable=True,
            note="Organization costs are readable when OPENAI_ADMIN_KEY is set.",
        ),
        default_max_tokens=4096,
    )
)

openai_responses = register(
    ProviderProfile(
        name="openai-responses",
        aliases=("responses", "gpt-responses"),
        display_name="OpenAI (Responses)",
        description="OpenAI's Responses API, for reasoning models.",
        signup_url="https://platform.openai.com/api-keys",
        access_path="api",
        auth_type="api_key",
        api_mode="responses",
        base_url_env="MARVI_OPENAI_URL",
        default_base_url="https://api.openai.com/v1",
        key_env=("OPENAI_API_KEY",),
        default_model_env="MARVI_OPENAI_RESPONSES_MODEL",
        default_model="gpt-5.2",
        default_aux_model="gpt-5.2-mini",
        default_vision_model="gpt-5.2",
        supports_vision=True,
        cache=CachePolicy(style="cache_key", min_tokens=1024),
        reasoning=ReasoningPolicy(
            style="effort", levels=("minimal", "low", "medium", "high"), default="low"
        ),
        limits=LimitPolicy(
            style="credit",
            readable=True,
            note="Shares OpenAI organization costs when OPENAI_ADMIN_KEY is set.",
        ),
        default_max_tokens=4096,
    )
)

codex = register(
    ProviderProfile(
        name="codex",
        aliases=("openai-codex", "chatgpt"),
        display_name="Codex (ChatGPT plan)",
        description="Codex through a ChatGPT subscription rather than the metered API.",
        signup_url="https://chatgpt.com/codex/pricing/",
        access_path="plan",
        auth_type="oauth_external",
        api_mode="responses",
        base_url_env="MARVI_CODEX_URL",
        default_base_url="https://chatgpt.com/backend-api/codex",
        # Populated by the OAuth flow rather than typed in by hand.
        key_env=("MARVI_CODEX_ACCESS_TOKEN",),
        default_model_env="MARVI_CODEX_MODEL",
        default_model="gpt-5.2-codex",
        default_aux_model="gpt-5.2-codex-mini",
        supports_vision=True,
        cache=CachePolicy(style="cache_key", min_tokens=1024),
        reasoning=ReasoningPolicy(
            style="effort", levels=("minimal", "low", "medium", "high"), default="low"
        ),
        limits=LimitPolicy(
            style="rolling_windows",
            windows=(("5 hours", 5), ("week", 168)),
            readable=False,
            note="Plan windows reset on a rolling basis. Exhaustion arrives as "
            "429 with Retry-After, which Marvi uses to cool the provider down.",
        ),
        default_max_tokens=4096,
    )
)
