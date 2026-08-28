"""The provider registry — the single source of truth for reaching a model.

Importing this package registers every provider Marvi knows about. Adding one
means adding a module here and nothing else: no base URL, model name, or key
belongs in application code.

Only the providers that are actually finished are registered. See
`docs/PROVIDERS.md` for what is implemented, what is planned, and what each one
needs before it can be used.
"""

from __future__ import annotations

# Registration happens on import; the modules are the registry.
from . import anthropic as _anthropic  # noqa: F401
from . import config, oauth
from . import local as _local  # noqa: F401
from . import metered as _metered  # noqa: F401
from . import openai as _openai  # noqa: F401
from . import opencode as _opencode  # noqa: F401
from .base import (
    ApiMode,
    CachePolicy,
    LimitPolicy,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderProfile,
    ReasoningPolicy,
    Usage,
    all_profiles,
    configured_profiles,
    get,
    register,
    select,
)
from .client import (
    AllProvidersExhaustedError,
    Completion,
    ProviderCallError,
    ProviderClient,
)

__all__ = [
    "AllProvidersExhaustedError",
    "ApiMode",
    "CachePolicy",
    "Completion",
    "LimitPolicy",
    "ProviderCallError",
    "ProviderClient",
    "ProviderError",
    "ProviderNotConfiguredError",
    "ProviderProfile",
    "ReasoningPolicy",
    "Usage",
    "all_profiles",
    "config",
    "configured_profiles",
    "get",
    "oauth",
    "register",
    "select",
]


#: Models observed to refuse `reasoning: {enabled: false}`.
#:
#: In memory for the process, because it is a property of the model rather than
#: of this machine and it is re-learned from the first refusal after a restart
#: -- one 400 that is already retried. Persisting it would mean a stale entry
#: outliving a model that changed.
_MANDATORY_REASONING: set[str] = set()


def mandatory_reasoning() -> set[str]:
    """Which models will not have their reasoning turned off.

    No catalog states this. OpenRouter lists `reasoning` in
    `supported_parameters` for a model that *requires* it exactly as for one
    that merely offers it, so the only place the difference appears is the
    refusal itself -- which is how `google/gemini-3.5-flash-lite` came to be
    running every background job while nothing said it could not be quietened.
    """
    return _MANDATORY_REASONING
