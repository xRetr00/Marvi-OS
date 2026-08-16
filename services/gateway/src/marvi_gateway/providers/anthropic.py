"""Anthropic, and the Claude Code plan.

The Messages API differs from chat completions in ways the profile already
handles: the system prompt sits beside the messages rather than inside them,
`max_tokens` is required, and authentication is `x-api-key` plus a version
header rather than a bearer token.

Caching is explicit here, and that is the interesting part. Anthropic does not
cache automatically — a prefix is only cached if it is marked with a
`cache_control` breakpoint, and a cache read is billed at roughly a tenth of a
fresh input token. For Marvi, whose system prompt, identity files and tool
schemas are byte-identical on every turn, marking that prefix is the single
largest cost saving available. Forgetting to mark it costs full price silently.
"""

from __future__ import annotations

from .base import CachePolicy, LimitPolicy, ProviderProfile, ReasoningPolicy, register

anthropic_api = register(
    ProviderProfile(
        name="anthropic",
        aliases=("claude", "anthropic-api"),
        display_name="Anthropic",
        description="Anthropic's metered API, billed per token.",
        signup_url="https://console.anthropic.com/settings/keys",
        access_path="api",
        auth_type="api_key",
        api_mode="anthropic",
        base_url_env="MARVI_ANTHROPIC_URL",
        default_base_url="https://api.anthropic.com",
        key_env=("ANTHROPIC_API_KEY",),
        default_model_env="MARVI_ANTHROPIC_MODEL",
        default_model="claude-sonnet-5",
        default_aux_model="claude-haiku-4-5-20251001",
        default_vision_model="claude-sonnet-5",
        supports_vision=True,
        # Explicit, and worth the effort: unmarked prefixes are never cached.
        cache=CachePolicy(style="explicit_breakpoints", min_tokens=1024, max_breakpoints=4),
        reasoning=ReasoningPolicy(style="budget_tokens"),
        limits=LimitPolicy(
            style="credit",
            readable=False,
            note="Credit and usage are shown in the Anthropic console.",
        ),
        default_max_tokens=4096,
    )
)

claude_code = register(
    ProviderProfile(
        name="claude-code",
        aliases=("claudecode", "claude-plan"),
        display_name="Claude Code (plan)",
        description="Claude through an Anthropic subscription rather than the metered API.",
        signup_url="https://claude.com/product/claude-code",
        access_path="plan",
        auth_type="oauth_external",
        api_mode="anthropic",
        base_url_env="MARVI_CLAUDE_CODE_URL",
        default_base_url="https://api.anthropic.com",
        key_env=("MARVI_CLAUDE_CODE_ACCESS_TOKEN",),
        default_model_env="MARVI_CLAUDE_CODE_MODEL",
        default_model="claude-sonnet-5",
        default_aux_model="claude-haiku-4-5-20251001",
        supports_vision=True,
        cache=CachePolicy(style="explicit_breakpoints", min_tokens=1024, max_breakpoints=4),
        reasoning=ReasoningPolicy(style="budget_tokens"),
        limits=LimitPolicy(
            style="rolling_windows",
            windows=(("5 hours", 5), ("week", 168)),
            readable=False,
            note="A 5-hour session window plus a weekly cap. Exhaustion arrives "
            "as 429 with Retry-After, which Marvi uses to cool the provider down.",
        ),
        default_max_tokens=4096,
    )
)
