"""Per-model reasoning capabilities and provider-specific request shaping.

Model list APIs are authoritative where they publish capabilities. OpenAI and
several compatible gateways do not, so the packaged fallback table records
vendor-documented model families. Unknown is deliberately empty: a picker that
offers a setting the model may reject is worse than no effort control.
"""

from __future__ import annotations

import fnmatch
import json
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .base import ProviderProfile

ALL_GATEWAY_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
_observed: dict[tuple[str, str], tuple[str, ...]] = {}


@lru_cache(maxsize=1)
def _rules() -> tuple[dict[str, Any], ...]:
    path = Path(__file__).with_name("model-capabilities.json")
    return tuple(json.loads(path.read_text(encoding="utf-8"))["rules"])


def _supported_flag(value: Any) -> bool:
    return value is True or (isinstance(value, dict) and value.get("supported") is True)


def from_entry(profile: ProviderProfile, entry: dict[str, Any]) -> tuple[str, ...] | None:
    """Read capabilities a provider publishes for this exact model."""
    if profile.name == "openrouter" and "reasoning" in entry:
        reasoning = entry.get("reasoning")
        if not isinstance(reasoning, dict):
            return ()
        published = reasoning.get("supported_efforts")
        levels = ALL_GATEWAY_EFFORTS if published is None else tuple(map(str, published or ()))
        if levels and not reasoning.get("mandatory") and "none" not in levels:
            levels = ("none", *levels)
        return levels
    if profile.name == "openrouter" and "supported_parameters" in entry:
        parameters = tuple(map(str, entry.get("supported_parameters") or ()))
        return ALL_GATEWAY_EFFORTS if any("reasoning" in value for value in parameters) else ()

    capabilities = entry.get("capabilities")
    if isinstance(capabilities, dict):
        reasoning = capabilities.get("reasoning")
        if isinstance(reasoning, dict) and isinstance(reasoning.get("allowed_options"), list):
            return tuple(map(str, reasoning["allowed_options"]))

        effort = capabilities.get("effort")
        if isinstance(effort, dict):
            levels = tuple(
                level
                for level in ("low", "medium", "high", "xhigh", "max")
                if _supported_flag(effort.get(level))
            )
            thinking = capabilities.get("thinking")
            if levels and isinstance(thinking, dict) and thinking.get("supported") is True:
                return ("none", *levels)
            if levels:
                return levels

    metadata = entry.get("metadata")
    tags = metadata.get("tags", []) if isinstance(metadata, dict) else entry.get("tags", [])
    if profile.name == "deepinfra" and any("reason" in str(tag).lower() for tag in tags or ()):
        return ("none", "low", "medium", "high")

    return None


def remember(provider: str, model: str, efforts: tuple[str, ...]) -> None:
    _observed[(provider, model)] = efforts


def forget(provider: str | None = None) -> None:
    if provider is None:
        _observed.clear()
        return
    for key in [key for key in _observed if key[0] == provider]:
        _observed.pop(key, None)


def supported(profile: ProviderProfile, model: str) -> tuple[str, ...]:
    key = (profile.name, model)
    if key in _observed:
        return _observed[key]
    lowered = model.lower()
    for rule in _rules():
        if profile.name in rule["providers"] and fnmatch.fnmatchcase(
            lowered, str(rule["pattern"]).lower()
        ):
            return tuple(map(str, rule["efforts"]))
    # Small synthetic profiles in adapters/tests can declare their exact
    # vocabulary directly. Registered providers use the table or observed
    # model metadata instead, so an unknown OpenAI model never inherits a
    # provider-wide guess.
    providers_in_table = {name for rule in _rules() for name in rule["providers"]}
    if profile.name not in providers_in_table or profile.name == "openrouter":
        return tuple(profile.reasoning.levels)
    return ()


def normalise(profile: ProviderProfile, model: str, value: str | None) -> str | None:
    asked = (value or "").strip().lower()
    return asked if asked and asked in supported(profile, model) else None


def apply(
    body: dict[str, Any],
    profile: ProviderProfile,
    model: str,
    value: str | None,
    *,
    force_off: bool = False,
) -> None:
    """Apply one supported selection in the provider's native wire shape."""
    choices = supported(profile, model)
    asked = ""
    if force_off:
        asked = "none" if "none" in choices else "off" if "off" in choices else ""
    else:
        asked = normalise(profile, model, value) or ""
    if not asked:
        return

    off = asked in {"none", "off"}
    transport = "high" if asked == "on" else "none" if asked == "off" else asked

    if profile.api_mode == "anthropic":
        if off:
            body["thinking"] = {"type": "disabled"}
        else:
            body["thinking"] = {"type": "adaptive"}
            body["output_config"] = {"effort": transport}
        return

    if profile.name == "openrouter":
        body["reasoning"] = {"effort": transport}
        return

    if profile.name == "deepseek":
        body["thinking"] = {"type": "disabled" if off else "enabled"}
        if not off:
            body["reasoning_effort"] = transport
        return

    if profile.api_mode == "responses":
        body["reasoning"] = {"effort": transport}
        return

    body["reasoning_effort"] = transport
