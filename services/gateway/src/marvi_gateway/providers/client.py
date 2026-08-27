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
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .base import (
    ProviderNotConfiguredError,
    ProviderProfile,
    Usage,
    configured_profiles,
    get,
)
from .usage import UsageLedger

logger = logging.getLogger(__name__)


def _merge_tool_calls(pending: dict[int, dict[str, Any]], fragments: list[Any]) -> None:
    """Reassemble streamed tool calls in place.

    A provider sends a tool call in pieces: the name once, then the argument
    JSON a few characters at a time, each tagged with the index of the call it
    belongs to. Concatenating by index is the whole job -- but the arguments
    are only valid JSON once the last fragment has arrived, which is why the
    caller sees them at the end of the round and not before.
    """
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        index = int(fragment.get("index") or 0)
        call = pending.setdefault(index, {"id": "", "name": "", "arguments": ""})
        if fragment.get("id"):
            call["id"] = fragment["id"]
        function = fragment.get("function") or {}
        if function.get("name"):
            call["name"] = function["name"]
        if function.get("arguments"):
            call["arguments"] += function["arguments"]


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
    ledger: UsageLedger = field(default_factory=UsageLedger)
    _pool: Any = None
    #: The last standing announced per provider, so a warning is written when
    #: something changes rather than every time it is asked about.
    _announced: dict[str, str] = field(default_factory=dict)

    # -- connections ---------------------------------------------------------

    def _client(self) -> Any:
        """One pooled client for the life of the process.

        Every call used to build its own `httpx.Client` and close it in a
        `finally`. Correct, and it threw away the connection each time: a fresh
        TCP and TLS handshake before the first token of every turn, and again
        on every tool round, which is up to eight per answer. That is the one
        measure both surfaces are judged on, spent on setup that was already
        paid for a moment earlier.

        An injected `http` still wins, because that is how the tests hand in a
        mock transport.
        """
        if self.http is not None:
            return self.http
        if self._pool is None:
            import httpx

            self._pool = httpx.Client(
                timeout=REQUEST_TIMEOUT,
                # Kept warm across turns, and bounded so an idle Marvi is not
                # holding sockets open to every provider it has ever tried.
                limits=httpx.Limits(
                    max_keepalive_connections=4,
                    max_connections=8,
                    keepalive_expiry=90.0,
                ),
            )
        return self._pool

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

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
        self.ledger.record(name, usage)

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
    def _reject(profile: Any, response: Any, *, body: str) -> ProviderCallError:
        """A 4xx that is about this request, not about the provider.

        Deliberately without a cooldown. A malformed request is ours, and the
        same provider answers the next well-formed one -- but the generic
        handler treated it as an outage and stood the provider down for five
        minutes. A background verdict nobody was waiting for could take the
        conversation offline, and did: every OpenRouter 400 in the logs is
        followed by the main model falling through to a provider whose key was
        dead, and then by "No provider is available".

        The body is carried into the error because httpx's own message is
        "Client error '400 Bad Request'" and nothing else, which says only that
        something in a request of several thousand characters was wrong.
        """
        detail = " ".join(body.split())[:400]
        logger.warning(
            "provider rejected the request; not cooling it down",
            extra={
                "marvi_provider": profile.name,
                "marvi_status": str(response.status_code),
                "marvi_body": detail,
            },
        )
        return ProviderCallError(
            f"{profile.name} rejected the request ({response.status_code}): {detail}"
        )

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
        model: str | None = None,
    ) -> Completion:
        """Call one provider. Raises rather than falling back — see `call_with_fallback`."""

        profile = (
            provider
            if isinstance(provider, ProviderProfile)
            else get(provider)
            if provider
            else None
        )
        if profile is None:
            raise ProviderCallError("no provider given")
        if not profile.configured():
            raise ProviderNotConfiguredError(f"{profile.name} is not configured")

        resting = self.resting(profile.name)
        if resting > 0:
            raise ProviderCallError(f"{profile.name} is cooling down for another {resting:.0f}s")

        # An explicit model wins over the provider's configured default. This
        # is how a session picks a model for itself without editing settings
        # everything else reads -- the override lives on the call, so nothing
        # about it survives the request.
        model = model or profile.model_for(job)  # type: ignore[arg-type]
        # An explicit effort wins; otherwise the provider's configured one.
        effort = effort or profile.effort_for()
        call_id = uuid4().hex[:12]
        started_at = time.perf_counter()
        diagnostic = {
            "marvi_call_id": call_id,
            "marvi_job": job,
            "marvi_provider": profile.name,
            "marvi_model": model,
            "marvi_message_count": len(messages),
            "marvi_input_chars": sum(len(str(message.get("content", ""))) for message in messages),
            "marvi_tool_count": len(tools or []),
            "marvi_max_tokens": max_tokens or 0,
        }
        logger.info("model call started", extra=diagnostic)
        try:
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
                job=job,
            )
        except Exception as exc:
            logger.warning(
                "model request build failed",
                extra={
                    **diagnostic,
                    "marvi_latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "marvi_error": str(exc)[:240],
                },
                exc_info=True,
            )
            raise ProviderCallError(f"{profile.name} request build failed: {exc}") from exc
        client = self._client()
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
            if 400 <= response.status_code < 500 and response.status_code != 408:
                raise self._reject(profile, response, body=response.text)
            response.raise_for_status()
            payload = response.json()
        except ProviderCallError as exc:
            logger.warning(
                "model call failed",
                extra={
                    **diagnostic,
                    "marvi_latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "marvi_error": str(exc)[:240],
                },
            )
            raise
        except Exception as exc:
            self.stand_down(profile.name, DEFAULT_COOLDOWN_SECONDS, f"call failed: {exc}"[:120])
            logger.warning(
                "model call failed",
                extra={
                    **diagnostic,
                    "marvi_latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "marvi_error": str(exc)[:240],
                },
                exc_info=True,
            )
            raise ProviderCallError(f"{profile.name} call failed: {exc}") from exc

        usage = profile.read_usage(payload)
        tool_calls = profile.read_tool_calls(payload)
        self.record(profile.name, usage)
        logger.info(
            "model call completed",
            extra={
                **diagnostic,
                "marvi_latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "marvi_input_tokens": usage.input,
                "marvi_output_tokens": usage.output,
                "marvi_cached_tokens": usage.cached_input,
                "marvi_billable_tokens": usage.billable,
                "marvi_tool_calls": len(tool_calls),
            },
        )
        return Completion(
            text=profile.read_text(payload),
            usage=usage,
            provider=profile.name,
            model=model,
            cached=usage.cached_input > 0,
            tool_calls=tool_calls,
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
        model: str | None = None,
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

        profile = (
            provider
            if isinstance(provider, ProviderProfile)
            else get(provider)
            if provider
            else None
        )
        if profile is None:
            raise ProviderCallError("no provider given")
        if not profile.configured():
            raise ProviderNotConfiguredError(f"{profile.name} is not configured")

        resting = self.resting(profile.name)
        if resting > 0:
            raise ProviderCallError(f"{profile.name} is cooling down for another {resting:.0f}s")

        # An explicit model wins over the provider's configured default. This
        # is how a session picks a model for itself without editing settings
        # everything else reads -- the override lives on the call, so nothing
        # about it survives the request.
        model = model or profile.model_for(job)  # type: ignore[arg-type]
        # An explicit effort wins; otherwise the provider's configured one.
        effort = effort or profile.effort_for()
        call_id = uuid4().hex[:12]
        started_at = time.perf_counter()
        diagnostic = {
            "marvi_call_id": call_id,
            "marvi_job": job,
            "marvi_provider": profile.name,
            "marvi_model": model,
            "marvi_message_count": len(messages),
            "marvi_input_chars": sum(len(str(message.get("content", ""))) for message in messages),
            "marvi_tool_count": len(tools or []),
            "marvi_max_tokens": max_tokens or 0,
        }
        logger.info("model stream started", extra=diagnostic)
        try:
            body = profile.build_request(
                messages,
                model=model,
                max_tokens=max_tokens,
                stream=True,
                effort=effort,
                cache_prefix=cache_prefix,
                temperature=temperature,
                tools=tools,
                job=job,
            )
        except Exception as exc:
            logger.warning(
                "model stream request build failed",
                extra={
                    **diagnostic,
                    "marvi_latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "marvi_error": str(exc)[:240],
                },
                exc_info=True,
            )
            raise ProviderCallError(f"{profile.name} stream request build failed: {exc}") from exc

        client = self._client()
        usage = Usage()
        # Tool calls arrive as fragments across many chunks and are only
        # meaningful once the round ends, so they are assembled here and
        # yielded whole at the end rather than dribbled out.
        pending_calls: dict[int, dict[str, Any]] = {}
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
                if 400 <= response.status_code < 500 and response.status_code != 408:
                    # Streamed, so the body has not been read yet.
                    response.read()
                    raise self._reject(profile, response, body=response.text)
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
                    elif piece.get("reasoning"):
                        # Kept apart from the answer all the way through.
                        # Reasoning must never be spoken, never sent to a TTS,
                        # and shown separately when it is shown at all.
                        yield {"reasoning": piece["reasoning"]}
                    elif piece.get("tool_calls"):
                        _merge_tool_calls(pending_calls, piece["tool_calls"])
        except ProviderCallError as exc:
            logger.warning(
                "model stream failed",
                extra={
                    **diagnostic,
                    "marvi_latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "marvi_error": str(exc)[:240],
                },
            )
            raise
        except Exception as exc:
            self.stand_down(profile.name, DEFAULT_COOLDOWN_SECONDS, f"call failed: {exc}"[:120])
            logger.warning(
                "model stream failed",
                extra={
                    **diagnostic,
                    "marvi_latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "marvi_error": str(exc)[:240],
                },
                exc_info=True,
            )
            raise ProviderCallError(f"{profile.name} stream failed: {exc}") from exc

        if pending_calls:
            yield {"tool_calls": [pending_calls[i] for i in sorted(pending_calls)]}

        # Recorded here rather than per chunk: a stream that was cut short still
        # cost whatever it produced, and this is the one place that knows.
        self.record(profile.name, usage)
        logger.info(
            "model stream completed",
            extra={
                **diagnostic,
                "marvi_latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "marvi_input_tokens": usage.input,
                "marvi_output_tokens": usage.output,
                "marvi_cached_tokens": usage.cached_input,
                "marvi_billable_tokens": usage.billable,
                "marvi_tool_calls": len(pending_calls),
            },
        )
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

    def _say_once(self, provider: str, state: str, message: str, *args: Any) -> None:
        """Warn when a provider's standing changes, not every time it is read.

        `candidates()` is a query and the status poll asks it every two
        seconds, so a warning per call wrote the same line eighteen hundred
        times an hour into the error log and buried everything else in it --
        including the three faults this was found while looking for.

        The event is the change. Repeating it is not more information.
        """
        if self._announced.get(provider) == state:
            return
        self._announced[provider] = state
        logger.warning(message, *args)

    def clear_notice(self, provider: str) -> None:
        """Forget a provider's last announced standing, so a return to normal
        is reported the next time something goes wrong."""
        self._announced.pop(provider, None)

    def candidates(self, preferred: str | None = None) -> list[ProviderProfile]:
        """Configured providers, preferred first, then local, then the rest.

        `MARVI_PROVIDER` is the standing preference and is honoured here when
        no explicit one is passed. It was not, which made choosing a provider
        do nothing: the list is sorted local-first, so a machine with LM Studio
        configured but not running tried it, waited for the connection to be
        refused, tried Ollama, waited again, and only then reached the provider
        the user had actually picked. Voice fared worse -- it takes the first
        usable candidate and got a local endpoint with no model name.
        """
        ready = [p for p in configured_profiles() if self.resting(p.name) <= 0]
        ready.sort(key=lambda p: 0 if p.access_path == "local" else 1)
        preferred = preferred or os.environ.get("MARVI_PROVIDER", "").strip() or None
        if preferred:
            try:
                chosen = get(preferred)
            except Exception:
                # A setting naming a provider that no longer exists is a stale
                # setting, not a reason to stop answering.
                logger.warning("ignoring unknown provider %r", preferred)
                return ready
            if not chosen.configured():
                self._say_once(
                    chosen.name,
                    "unconfigured",
                    "%s is selected but not configured; falling back",
                    chosen.name,
                )
                return ready
            if self.resting(chosen.name) > 0:
                # Cooling down. Falling through is the point of a cooldown --
                # but it is the only case that overrides an explicit choice.
                self._say_once(
                    chosen.name, "cooling", "%s is cooling down; falling back", chosen.name
                )
                return [p for p in ready if p.name != chosen.name]

            # Locked. A provider chosen in the Models page answers, or nothing
            # does. Keeping the others behind it meant a turn could quietly be
            # answered by something the user never picked -- which is how
            # replies came back from LM Studio while the page said OpenRouter,
            # and why the same turn could use a different model each time.
            return [chosen]
        return ready

    def stream_with_fallback(
        self, messages: list[dict[str, Any]], preferred: str | None = None, **kwargs: Any
    ) -> Iterator[dict[str, Any]]:
        """Stream from the first provider that answers.

        Fallback happens *before the first delta* and is a hard error after it.
        Once bytes have reached the caller, moving to another provider is no
        longer transparent: the user has already seen half a sentence, and
        silently continuing it in a different model's voice is worse than
        failing. So the first chunk is what commits the choice.

        The provider that answered is announced as `{"provider": name}` before
        any content, because the caller cannot know it in advance and has to
        attribute what follows.
        """
        attempts = self.candidates(preferred)
        if not attempts:
            raise AllProvidersExhaustedError(
                "No provider is available; all are unconfigured or cooling down."
            )

        last: Exception | None = None
        for profile in attempts:
            started = False
            try:
                for event in self.stream(messages, provider=profile, **kwargs):
                    if not started:
                        started = True
                        yield {"provider": profile.name}
                    yield event
                return
            except Exception as exc:
                if started:
                    # Committed. The caller has seen this provider's words.
                    raise
                logger.warning("provider %s could not start: %s", profile.name, exc)
                last = exc

        raise ProviderCallError(f"No provider could start a stream; last error: {last}")

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
        logger.info(
            "model fallback route resolved",
            extra={
                "marvi_streaming": False,
                "marvi_preferred": preferred or "auto",
                "marvi_candidates": ",".join(profile.name for profile in attempts),
                "marvi_job": str(kwargs.get("job", "main")),
                "marvi_model": str(kwargs.get("model", "auto") or "auto"),
            },
        )
        for profile in attempts:
            try:
                return self.call(messages, provider=profile, **kwargs)
            except ProviderCallError as exc:
                logger.warning(
                    "model fallback attempt failed",
                    extra={
                        "marvi_provider": profile.name,
                        "marvi_job": str(kwargs.get("job", "main")),
                        "marvi_error": str(exc)[:240],
                    },
                )
                last = exc
                continue
        raise AllProvidersExhaustedError(f"every provider failed; last error: {last}")
