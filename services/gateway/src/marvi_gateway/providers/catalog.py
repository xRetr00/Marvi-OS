"""What models a provider actually has, asked rather than assumed.

Typing a model name into a text box is a guess with no feedback: a typo is
indistinguishable from a model that was retired, and both surface later as a
failed call with a provider's own error message. Every provider here publishes
a list, so the list is what the UI offers.

Three shapes, one row type. OpenAI-compatible endpoints return `{"data":
[{"id": ...}]}`; Anthropic returns the same envelope with a `display_name`;
OpenRouter returns considerably more -- pricing, context length, and
`supported_parameters`, which is the only place any provider states per model
whether it can reason. That last one is why effort cannot be a provider-wide
setting for a gateway: OpenRouter fronts models that reason and models that do
not, under one credential.

What is *not* here: which upstream serves an OpenRouter model. That is a
second question with different data behind it and lives in `openrouter.py`.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from ..logs import get_logger
from .base import ProviderProfile

log = get_logger("providers")

LIST_TIMEOUT = 10.0

#: Model lists change on the order of weeks, and the page that shows them opens
#: far more often than that. Long enough to make the picker feel instant,
#: short enough that a model added today is selectable today.
CACHE_SECONDS = 900.0

#: Name fragments that mark a model built for speed rather than depth. Used to
#: suggest a voice model, never to restrict one: the user's choice always
#: stands, and this only decides what is offered when nothing has been chosen.
LIGHT_TIER = ("flash", "lite", "mini", "small", "turbo", "instant", "haiku", "nano")

_cache: dict[str, tuple[float, list[ModelCard]]] = {}


@dataclass(frozen=True)
class ModelCard:
    """One selectable model, in the terms the picker needs to sort and label."""

    id: str
    name: str
    provider: str
    context: int = 0
    #: Empty when the model cannot reason, so the UI can hide the effort
    #: control rather than offering a setting the model will ignore.
    efforts: tuple[str, ...] = ()
    prompt_per_million: float | None = None
    completion_per_million: float | None = None
    vision: bool = False

    @property
    def reasons(self) -> bool:
        return bool(self.efforts)

    @property
    def light(self) -> bool:
        """Built for speed rather than depth, by its own name.

        A heuristic on the name, and deliberately only that: no provider
        publishes a "fast" flag, and the vendors are consistent enough about
        flash/mini/lite/haiku that the name is the best signal there is. It
        suggests, never restricts.
        """
        lowered = self.id.lower()
        return any(mark in lowered for mark in LIGHT_TIER)

    def as_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["efforts"] = list(self.efforts)
        row["reasons"] = self.reasons
        row["light"] = self.light
        return row


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _per_million(value: Any) -> float | None:
    price = _number(value)
    return None if price is None else round(price * 1_000_000, 3)


def _card(entry: dict[str, Any], profile: ProviderProfile) -> ModelCard | None:
    if entry.get("type") == "embedding":
        return None
    identifier = str(entry.get("id") or entry.get("key") or entry.get("name") or "").strip()
    if not identifier:
        return None

    pricing = entry.get("pricing") or {}
    modalities = ((entry.get("architecture") or {}).get("input_modalities")) or []
    capabilities = entry.get("capabilities") or {}
    metadata = entry.get("metadata") or {}

    from . import effort

    published = effort.from_entry(profile, entry)
    efforts = published if published is not None else effort.supported(profile, identifier)
    effort.remember(profile.name, identifier, tuple(efforts))

    return ModelCard(
        id=identifier,
        name=str(entry.get("display_name") or entry.get("name") or identifier),
        provider=profile.name,
        context=int(
            _number(
                entry.get("context_length")
                or entry.get("context_window")
                or entry.get("max_input_tokens")
                or entry.get("max_context_length")
                or metadata.get("context_length")
            )
            or 0
        ),
        efforts=tuple(efforts),
        prompt_per_million=_per_million(pricing.get("prompt")),
        completion_per_million=_per_million(pricing.get("completion")),
        vision=("image" in modalities)
        or capabilities.get("vision") is True
        or bool(profile.supports_vision and not modalities and not capabilities),
    )


def _models_url(profile: ProviderProfile) -> str:
    """Use richer local catalog endpoints when the server publishes them."""
    base = profile.base_url()
    if profile.name == "lmstudio":
        return f"{base.removesuffix('/v1')}/api/v1/models"
    if profile.name == "ollama":
        return f"{base.removesuffix('/v1')}/api/tags"
    return f"{base}{profile.models_path}"


def fetch(profile: ProviderProfile, http: Any = None) -> list[ModelCard]:
    """Ask the provider what it has. Never raises; an empty list is the answer.

    Empty rather than an error because this feeds a picker: a provider being
    unreachable should leave the field typeable, not break the page. The caller
    can tell the two apart -- a configured provider returning nothing is worth
    saying out loud, and the endpoint does.
    """
    import httpx

    base = profile.base_url()
    if not base:
        return []

    client = http or httpx.Client(timeout=LIST_TIMEOUT)
    try:
        response = client.get(_models_url(profile), headers=profile.headers())
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        log.warning("could not list models for %s: %s", profile.name, exc)
        return []
    finally:
        if http is None:
            client.close()

    entries = (
        payload.get("data") or payload.get("models")
        if isinstance(payload, dict)
        else payload
    )
    if not isinstance(entries, list):
        log.warning("unexpected model list shape from %s", profile.name)
        return []

    cards = [
        card for entry in entries if isinstance(entry, dict) and (card := _card(entry, profile))
    ]
    cards.sort(key=lambda card: card.id)
    return cards


def models(profile: ProviderProfile, *, http: Any = None, refresh: bool = False) -> list[ModelCard]:
    """`fetch`, but at most once every [`CACHE_SECONDS`][] per provider."""
    now = time.monotonic()
    hit = _cache.get(profile.name)
    if hit and not refresh and now - hit[0] < CACHE_SECONDS:
        return hit[1]

    cards = fetch(profile, http=http)
    if cards or not hit:
        # A failed refresh keeps the last good list rather than emptying the
        # picker: a provider blipping should not look like a provider with no
        # models.
        _cache[profile.name] = (now, cards)
        return cards
    return hit[1]


def known_context(provider: str, model: str) -> int:
    """The model's context window, if it is already known. Never fetches.

    Read from what a previous listing cached rather than by asking. This is
    called while assembling a prompt, and a network round trip there would put
    the provider's availability in front of every turn -- so an unknown model
    simply reports 0 and the caller uses its default.
    """
    for age, cards in ((_cache.get(provider) or (0.0, [])),):
        del age
        for card in cards:
            if card.id == model:
                return int(card.context or 0)
    return 0


def known_vision(provider: str, model: str) -> bool | None:
    """Cached per-model image capability, or None when the model is unknown."""
    for _age, cards in ((_cache.get(provider) or (0.0, [])),):
        for card in cards:
            if card.id == model:
                return bool(card.vision)
    return None


def forget(name: str | None = None) -> None:
    """Drop cached lists — after a credential changes, or on explicit refresh."""
    from . import effort

    effort.forget(name)
    if name is None:
        _cache.clear()
    else:
        _cache.pop(name, None)
