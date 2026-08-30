"""OpenCode: two providers, not one.

Zen and Go share a vendor and nothing else that matters here.

* **Zen** is pay-as-you-go against credit, at `/zen/v1`.
* **Go** is a $10/month plan at `/zen/go/v1`, with three rolling caps —
  $12 per 5 hours, $30 per week, $60 per month.

They bill differently, fail differently, and live at different base URLs, so
they are separate profiles. Collapsing them behind a flag would mean the UI
could not tell the user which limit they were about to hit.

Neither publishes usage over the API — consumption is visible only in the
OpenCode console — so the limit policy is marked unreadable and Marvi falls
back to its own token counting. That is exactly why budget control is
token-denominated rather than built on provider-reported spend.
"""

from __future__ import annotations

from .base import (
    MARVI_APP_NAME,
    MARVI_APP_URL,
    CachePolicy,
    LimitPolicy,
    ProviderProfile,
    register,
)

_ATTRIBUTION = {"HTTP-Referer": MARVI_APP_URL, "X-Title": MARVI_APP_NAME}

zen = register(
    ProviderProfile(
        name="opencode-zen",
        aliases=("zen", "opencode_zen"),
        display_name="OpenCode Zen",
        description="Pay-as-you-go access to open models, billed against credit.",
        signup_url="https://opencode.ai/auth",
        access_path="api",
        auth_type="api_key",
        api_mode="chat_completions",
        base_url_env="MARVI_OPENCODE_ZEN_URL",
        default_base_url="https://opencode.ai/zen/v1",
        key_env=("OPENCODE_ZEN_API_KEY",),
        default_model_env="MARVI_OPENCODE_ZEN_MODEL",
        default_model="glm-5",
        default_aux_model="gemini-3-flash",
        default_headers=dict(_ATTRIBUTION),
        cache=CachePolicy(style="cache_key", min_tokens=1024),
        limits=LimitPolicy(
            style="credit",
            readable=False,
            note="Credit balance is shown in the OpenCode console.",
        ),
        default_max_tokens=4096,
    )
)

go = register(
    ProviderProfile(
        name="opencode-go",
        aliases=("go", "opencode_go", "opencode"),
        display_name="OpenCode Go",
        description="$10/month plan with rolling 5-hour, weekly and monthly caps.",
        signup_url="https://opencode.ai/docs/go/",
        access_path="plan",
        auth_type="api_key",
        api_mode="chat_completions",
        base_url_env="MARVI_OPENCODE_GO_URL",
        default_base_url="https://opencode.ai/zen/go/v1",
        key_env=("OPENCODE_GO_API_KEY",),
        default_model_env="MARVI_OPENCODE_GO_MODEL",
        default_model="deepseek-v4-flash",
        # The plan's own cheap model, so auxiliary work does not burn the cap
        # on a large model.
        default_aux_model="glm-5",
        default_headers=dict(_ATTRIBUTION),
        cache=CachePolicy(style="cache_key", min_tokens=1024),
        limits=LimitPolicy(
            style="rolling_windows",
            windows=(("5 hours", 5), ("week", 168), ("month", 720)),
            readable=False,
            note="Caps are $12 / 5h, $30 / week, $60 / month. "
            "Usage is published only in the OpenCode console, so Marvi shows "
            "its own token count instead.",
        ),
        default_max_tokens=4096,
    )
)
