"""The one place a model actually gets called.

Every request in Marvi goes through here, which is what makes three otherwise
separate concerns fall out of one implementation:

* **Token accounting.** Usage is recorded per call in the provider's own shape
  and normalised, so the budget in `REAL-AGENCY.md` binds identically on a
  metered API, a plan, and a local model.
* **Cooldown.** A 429 with `Retry-After` is a window-exhaustion signal, not a
  reason to retry. The provider is stood down until its window resets. Retrying
  into a rate limit is how an assistant turns one exhausted plan into a
  quota-burning loop.
* **Failover.** With providers cooled down rather than hammered, falling through
  to the next configured one is simply picking the first that is not resting.

Streaming is not implemented here on purpose. The voice path streams through
LiveKit's own client, which already owns interruption and playout; this client
serves the background mind, which has nobody waiting on a first token.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from .base import (
    ProviderNotConfiguredError,
    ProviderProfile,
    Usage,
    configured_profiles,
    get,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 60.0
DEFAULT_COOLDOWN_SECONDS = 300.0
MAX_COOLDOWN_SECONDS = 6 * 60 * 60


class ProviderCallError(Exception):
    """The call failed in a way the caller should see."""


class AllProvidersExhaustedError(ProviderCallError):
    """Every candidate was cooling down or failed."""


@dataclass
class Completion:
    text: str
    usage: Usage
    provider: str
    model: str
    cached: bool = False
    # Requested, never executed. The caller routes these through the tool
    # router so confirmation applies identically to every surface.
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _Cooldown:
    until: float
    reason: str


@dataclass
class ProviderClient:
    """Calls models, counts tokens, and stands providers down when told to."""

    http: Any = None
    _cooldowns: dict[str, _Cooldown] = field(default_factory=dict)
    _usage: dict[str, Usage] = field(default_factory=dict)

    # -- cooldown ------------------------------------------------------------

    def resting(self, name: str, now: float | None = None) -> float:
        """Seconds until this provider may be used again; 0 when available."""
        entry = self._cooldowns.get(name)
        if entry is None:
            return 0.0
        remaining = entry.until - (now if now is not None else time.monotonic())
        if remaining <= 0:
            del self._cooldowns[name]
            return 0.0
        return remaining

    def stand_down(self, name: str, seconds: float, reason: str) -> None:
        seconds = max(1.0, min(float(seconds), MAX_COOLDOWN_SECONDS))
        self._cooldowns[name] = _Cooldown(time.monotonic() + seconds, reason)
        logger.warning("provider %s cooling down %.0fs: %s", name, seconds, reason)

    def clear_cooldown(self, name: str) -> None:
        """Let a provider be tried again now — used when its settings change."""
        self._cooldowns.pop(name, None)

    def cooldowns(self) -> dict[str, dict[str, Any]]:
        return {
            name: {"seconds_remaining": round(self.resting(name), 1), "reason": entry.reason}
            for name, entry in list(self._cooldowns.items())
            if self.resting(name) > 0
        }

    # -- accounting ----------------------------------------------------------

    def record(self, name: str, usage: Usage) -> None:
        self._usage[name] = self._usage.get(name, Usage()) + usage

    def usage(self, name: str | None = None) -> Usage:
        if name:
            return self._usage.get(name, Usage())
        total = Usage()
        for entry in self._usage.values():
            total = total + entry
        return total

    def usage_by_provider(self) -> dict[str, dict[str, int]]:
        return {
            name: {
                "input": u.input,
                "output": u.output,
                "cached_input": u.cached_input,
                "billable": u.billable,
            }
            for name, u in self._usage.items()
        }

    # -- calling -------------------------------------------------------------

    @staticmethod
    def _retry_after(response: Any) -> float:
        header = (response.headers or {}).get("retry-after") if response is not None else None
        try:
            return float(header)
        except (TypeError, ValueError):
            return DEFAULT_COOLDOWN_SECONDS

    def call(
        self,
        messages: list[dict[str, Any]],
        provider: str | ProviderProfile | None = None,
        job: str = "main",
        max_tokens: int | None = None,
        effort: str | None = None,
        cache_prefix: bool = True,
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> Completion:
        """Call one provider. Raises rather than falling back — see `call_with_fallback`."""
        import httpx

        profile = provider if isinstance(provider, ProviderProfile) else get(provider) if provider else None
        if profile is None:
            raise ProviderCallError("no provider given")
        if not profile.configured():
            raise ProviderNotConfiguredError(f"{profile.name} is not configured")

        resting = self.resting(profile.name)
        if resting > 0:
            raise ProviderCallError(
                f"{profile.name} is cooling down for another {resting:.0f}s"
            )

        model = profile.model_for(job)  # type: ignore[arg-type]
        body = profile.build_request(
            messages,
            model=model,
            max_tokens=max_tokens,
            stream=False,
            effort=effort,
            # Caching is on by default: the prefix is identical every turn and
            # not asking for it is a silent cost.
            cache_prefix=cache_prefix,
            temperature=temperature,
            tools=tools,
        )
        client = self.http or httpx.Client(timeout=REQUEST_TIMEOUT)
        try:
            response = client.post(profile.endpoint(), json=body, headers=profile.headers())
            if response.status_code == 429:
                wait = self._retry_after(response)
                self.stand_down(profile.name, wait, "rate limited or window exhausted")
                raise ProviderCallError(f"{profile.name} is rate limited")
            if response.status_code in (401, 403):
                # A dead credential will not fix itself on retry.
                self.stand_down(profile.name, MAX_COOLDOWN_SECONDS, "authentication rejected")
                raise ProviderCallError(f"{profile.name} rejected the credential")
            response.raise_for_status()
            payload = response.json()
        except ProviderCallError:
            raise
        except Exception as exc:
            self.stand_down(profile.name, DEFAULT_COOLDOWN_SECONDS, f"call failed: {exc}"[:120])
            raise ProviderCallError(f"{profile.name} call failed: {exc}") from exc
        finally:
            if self.http is None:
                client.close()

        usage = profile.read_usage(payload)
        self.record(profile.name, usage)
        return Completion(
            text=profile.read_text(payload),
            usage=usage,
            provider=profile.name,
            model=model,
            cached=usage.cached_input > 0,
            tool_calls=profile.read_tool_calls(payload),
        )

    def stream(
        self,
        messages: list[dict[str, Any]],
        provider: str | ProviderProfile | None = None,
        job: str = "main",
        max_tokens: int | None = None,
        effort: str | None = None,
        cache_prefix: bool = True,
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Call one provider and yield deltas as they arrive.

        `call` waits for the whole response before returning a word, which is
        why chat shows nothing until the model has finished thinking and why
        the voice path could never have used it. Same policy — cooldowns,
        credential handling, usage — applied to a response read incrementally.

        Yields plain dicts rather than a provider's own chunk shape, because
        two callers with different SDKs consume this: `{"delta": str}` for
        text, then a final `{"done": True, "usage": {...}}`.
        """
        import httpx

        profile = provider if isinstance(provider, ProviderProfile) else get(provider) if provider else None
        if profile is None:
            raise ProviderCallError("no provider given")
        if not profile.configured():
            raise ProviderNotConfiguredError(f"{profile.name} is not configured")

        resting = self.resting(profile.name)
        if resting > 0:
            raise ProviderCallError(f"{profile.name} is cooling down for another {resting:.0f}s")

        model = profile.model_for(job)  # type: ignore[arg-type]
        body = profile.build_request(
            messages,
            model=model,
            max_tokens=max_tokens,
            stream=True,
            effort=effort,
            cache_prefix=cache_prefix,
            temperature=temperature,
            tools=tools,
        )

        client = self.http or httpx.Client(timeout=REQUEST_TIMEOUT)
        usage = Usage()
        try:
            with client.stream(
                "POST", profile.endpoint(), json=body, headers=profile.headers()
            ) as response:
                if response.status_code == 429:
                    wait = self._retry_after(response)
                    self.stand_down(profile.name, wait, "rate limited or window exhausted")
                    raise ProviderCallError(f"{profile.name} is rate limited")
                if response.status_code in (401, 403):
                    self.stand_down(profile.name, MAX_COOLDOWN_SECONDS, "authentication rejected")
                    raise ProviderCallError(f"{profile.name} rejected the credential")
                response.raise_for_status()

                for line in response.iter_lines():
                    piece = profile.read_stream_line(line)
                    if piece is None:
                        continue
                    if piece.get("usage"):
                        usage = profile.read_usage(piece["usage"])
                        continue
                    if piece.get("delta"):
                        yield {"delta": piece["delta"]}
        except ProviderCallError:
            raise
        except Exception as exc:
            self.stand_down(profile.name, DEFAULT_COOLDOWN_SECONDS, f"call failed: {exc}"[:120])
            raise ProviderCallError(f"{profile.name} stream failed: {exc}") from exc
        finally:
            if self.http is None:
                client.close()

        # Recorded here rather than per chunk: a stream that was cut short still
        # cost whatever it produced, and this is the one place that knows.
        self.record(profile.name, usage)
        yield {
            "done": True,
            "provider": profile.name,
            "model": model,
            "usage": {
                "input": usage.input,
                "output": usage.output,
                "cached_input": usage.cached_input,
                "billable": usage.billable,
            },
        }

    def reachable(self, profile: ProviderProfile, timeout: float = 0.4) -> bool:
        """Is there actually a server there?

        Only meaningful for local providers: they count as configured the moment
        they have a URL, so two of them are always "ready" even when neither is
        running. For a hosted provider the credential is the check.

        The timeout is short on purpose. A server on this machine answers in
        milliseconds; anything slower is a firewall silently dropping the
        connection, and waiting a full second for that three times over is a
        second of nothing on every voice session start.
        """
        if profile.access_path != "local":
            return True
        import httpx

        try:
            client = self.http or httpx.Client(timeout=timeout)
            try:
                return client.get(f"{profile.base_url()}/models").status_code < 500
            finally:
                if self.http is None:
                    client.close()
        except Exception:
            return False

    def candidates(self, preferred: str | None = None) -> list[ProviderProfile]:
        """Configured providers, preferred first, then local, then the rest."""
        ready = [p for p in configured_profiles() if self.resting(p.name) <= 0]
        ready.sort(key=lambda p: 0 if p.access_path == "local" else 1)
        if preferred:
            chosen = get(preferred)
            ready = [p for p in ready if p.name != chosen.name]
            if chosen.configured() and self.resting(chosen.name) <= 0:
                ready.insert(0, chosen)
        return ready

    def call_with_fallback(
        self, messages: list[dict[str, Any]], preferred: str | None = None, **kwargs: Any
    ) -> Completion:
        """Try providers in order until one answers.

        A provider that fails is already cooling down by the time we move on, so
        the next attempt does not come back to it.
        """
        attempts = self.candidates(preferred)
        if not attempts:
            raise AllProvidersExhaustedError(
                "No provider is available; all are unconfigured or cooling down."
            )
        last: Exception | None = None
        for profile in attempts:
            try:
                return self.call(messages, provider=profile, **kwargs)
            except ProviderCallError as exc:
                last = exc
                continue
        raise AllProvidersExhaustedError(f"every provider failed; last error: {last}")
