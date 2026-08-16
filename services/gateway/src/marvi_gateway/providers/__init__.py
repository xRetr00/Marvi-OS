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
from . import local as _local  # noqa: F401
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

__all__ = [
    "ApiMode",
    "CachePolicy",
    "LimitPolicy",
    "ProviderError",
    "ProviderNotConfiguredError",
    "ProviderProfile",
    "ReasoningPolicy",
    "Usage",
    "all_profiles",
    "configured_profiles",
    "get",
    "register",
    "select",
]
