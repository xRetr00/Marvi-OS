"""OpenRouter's second layer: choosing who actually serves the model.

OpenRouter is a gateway, not a model host. Ask it for `anthropic/claude-sonnet-5`
and several upstream providers can answer — each with its own price, its own
throughput, and its own time to first token. By default OpenRouter picks the
cheapest reliable one, weighted by the inverse square of price.

For voice that default is the wrong one. Cheapest is frequently not fastest, and
first-token latency is the whole experience of a voice turn: the words either
start quickly or Marvi feels slow. So the route is a choice Marvi makes per job
rather than a default it accepts.

Two ways to make it, and both belong to the user:

* **A policy** — "fastest", "cheapest", "most throughput" — which OpenRouter
  resolves per request against live numbers. Right for voice, where the fastest
  provider this minute is a better answer than one pinned last week.
* **A named list** — pin exact providers in order. Right when a particular one
  is known good, or a particular one is known bad.

`endpoints()` reads what OpenRouter publishes per upstream — price always,
latency and throughput where it has them — so a choice can be made against
numbers rather than a guess.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from ..logs import get_logger

log = get_logger("providers")

#: How a request should be routed when no explicit provider list is given.
#: `auto` sends nothing and lets OpenRouter apply its own default.
POLICIES = {
    "auto": "",
    "cheapest": "price",
    "fastest": "latency",
    "throughput": "throughput",
}

#: Voice is the surface that cares. Latency-sorted rather than price-sorted,
#: because a cheap provider that takes two seconds to start speaking has cost
#: the thing voice exists for.
DEFAULT_POLICY_FOR_JOB = {"main": "auto", "voice": "fastest"}

ENDPOINTS_TIMEOUT = 8.0


@dataclass(frozen=True)
class Route:
    """What to ask OpenRouter for, beyond the model."""

    #: One of POLICIES. Ignored when `order` is set and fallbacks are off.
    policy: str = "auto"
    #: Exact upstream slugs, most preferred first.
    order: tuple[str, ...] = ()
    #: Never use these, whatever the policy says.
    ignore: tuple[str, ...] = ()
    #: False pins the request to `order` and fails rather than straying. True
    #: keeps OpenRouter's failover, which is usually what you want — a pinned
    #: provider having an outage should not take Marvi down with it.
    allow_fallbacks: bool = True

    def as_body(self) -> dict[str, Any]:
        """The `provider` object for a chat completions request, or empty.

        Empty rather than a default-shaped object: sending `{}` is a request to
        route with no preferences, which is not the same as not asking, and the
        difference has shown up as surprising behaviour in other gateways.
        """
        body: dict[str, Any] = {}
        sort = POLICIES.get(self.policy, "")
        if sort:
            body["sort"] = sort
        if self.order:
            body["order"] = list(self.order)
        if self.ignore:
            body["ignore"] = list(self.ignore)
        if not self.allow_fallbacks:
            body["allow_fallbacks"] = False
        return body


def _slugs(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def route_for(job: str = "main") -> Route:
    """The route this job should use, from the user's settings.

    Per job, because the right answer differs: voice wants the fastest
    provider and a batch summarisation would rather have the cheapest. The
    environment is the store, as it is for every other provider setting, so the
    GUI edits the same values everything else reads.
    """
    default = DEFAULT_POLICY_FOR_JOB.get(job, "auto")
    policy = os.environ.get(f"MARVI_OPENROUTER_ROUTE_{job.upper()}", "").strip().lower()
    if not policy:
        policy = os.environ.get("MARVI_OPENROUTER_ROUTE", "").strip().lower()
    if policy not in POLICIES:
        if policy:
            log.warning(
                "unknown OpenRouter route %r; using %s", policy, default
            )
        policy = default

    return Route(
        policy=policy,
        order=_slugs(os.environ.get("MARVI_OPENROUTER_PROVIDERS", "")),
        ignore=_slugs(os.environ.get("MARVI_OPENROUTER_IGNORE", "")),
        # Opt out explicitly. Pinning without fallback means an upstream outage
        # becomes Marvi's outage, so it is never the default.
        allow_fallbacks=os.environ.get("MARVI_OPENROUTER_PIN", "").strip().lower()
        not in ("1", "true", "yes", "on"),
    )


def endpoints(model: str, api_key: str | None = None, http: Any = None) -> list[dict[str, Any]]:
    """Who can serve this model, and on what terms.

    Returns one row per upstream with the numbers that decide between them.

    Price is always there. Latency and throughput often are not — OpenRouter
    publishes them per endpoint and leaves them null for many, so they come
    back as None and the UI has to say "unknown" rather than "0". Uptime is
    reliably present. Checked against the live API rather than assumed: of the
    nine endpoints serving Claude Sonnet 5, all nine priced, none with latency.

    That is also the argument for the `fastest` *policy* over a pinned list:
    OpenRouter can sort by a latency it measures internally even where it does
    not publish the number.
    """
    import httpx

    if "/" not in model:
        # OpenRouter model ids are `vendor/model`; anything else is a local name
        # that this endpoint knows nothing about.
        return []

    client = http or httpx.Client(timeout=ENDPOINTS_TIMEOUT)
    headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = client.get(
            f"https://openrouter.ai/api/v1/models/{model}/endpoints", headers=headers
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        log.warning("could not list OpenRouter endpoints for %s: %s", model, exc)
        return []
    finally:
        if http is None:
            client.close()

    rows = []
    for entry in (payload.get("data") or {}).get("endpoints") or []:
        pricing = entry.get("pricing") or {}
        rows.append(
            {
                # `tag` is the slug routing accepts; `provider_name` is the one
                # a person recognises. Both, because the UI shows one and sends
                # the other.
                "slug": str(entry.get("tag") or ""),
                "name": str(entry.get("provider_name") or entry.get("name") or ""),
                "context": int(entry.get("context_length") or 0),
                "quantization": str(entry.get("quantization") or ""),
                # Per million tokens: the per-token figures are small enough
                # that a table of them is unreadable.
                "prompt_per_million": _per_million(pricing.get("prompt")),
                "completion_per_million": _per_million(pricing.get("completion")),
                "latency_ms": _number(entry.get("latency_last_30m")),
                "throughput": _number(entry.get("throughput_last_30m")),
                "uptime": _number(entry.get("uptime_last_30m")),
            }
        )
    return rows


def _number(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _per_million(value: Any) -> float | None:
    try:
        return round(float(value) * 1_000_000, 3)
    except (TypeError, ValueError):
        return None
