"""Connected-account context and actions via the official Composio SDK.

Marvi OS holds no provider credentials and runs no OAuth flow. Composio owns
the connections; this module is a thin client over its SDK, normalising the
call surface and error shapes so the tool router does not learn SDK internals.

Everything Composio returns is content written by other people. It is handed
back through `untrusted.wrap_external`, never as bare text.

Verified against composio 0.19.0 / composio-client 1.43.0 on a live account:
`Composio(api_key=...)`, `connected_accounts.list(user_ids=[...], limit=...)`
yielding `.items[].toolkit.slug` and `.status`, and
`tools.execute(slug=..., arguments=..., user_id=...)`.
"""

from __future__ import annotations

import os
import time
from typing import Any

from .untrusted import wrap_external

DEFAULT_USER_ID = "default"
# The runtime snapshot is polled every 2s; connections are a network call.
CONNECTIONS_CACHE_SECONDS = 60.0
# Composio reports these for a connection that still exists but no longer works.
DEAD_STATUSES = {"expired", "revoked", "failed", "disabled", "inactive"}
LIVE_STATUSES = {"active", "connected", "success"}

GMAIL_FETCH = "GMAIL_FETCH_EMAILS"
GMAIL_SEND = "GMAIL_SEND_EMAIL"
CALENDAR_EVENTS = "GOOGLECALENDAR_EVENTS_LIST"


class AccountsUnavailableError(Exception):
    """No API key, or the SDK is not installed. Not a per-account problem."""


class AccountAuthError(Exception):
    """The key was rejected, or the account's own authorisation is gone."""


class AccountRateLimitedError(Exception):
    pass


class AccountTransientError(Exception):
    pass


def api_key() -> str | None:
    return (os.environ.get("COMPOSIO_API_KEY") or "").strip() or None


def _status_of(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )


def _reraise(exc: Exception) -> None:
    """Normalise SDK/HTTP failures so callers never branch on SDK internals."""
    status = _status_of(exc)
    if status == 429:
        raise AccountRateLimitedError("Composio rate limit reached.") from exc
    if status in (401, 403):
        raise AccountAuthError(f"Composio rejected the request ({status}).") from exc
    if isinstance(status, int) and status >= 500:
        raise AccountTransientError(f"Composio server error ({status}).") from exc
    raise AccountTransientError(str(exc)) from exc


def _as_dict(result: Any) -> Any:
    for attr in ("model_dump", "dict", "to_dict"):
        method = getattr(result, attr, None)
        if callable(method):
            try:
                return method()
            except Exception:
                continue
    return result if isinstance(result, (dict, list, str, int, float, bool, type(None))) else str(result)


class ComposioAccounts:
    def __init__(
        self, key: str | None = None, client: Any = None, user_id: str = DEFAULT_USER_ID
    ) -> None:
        self._key = key if key is not None else api_key()
        self._client = client
        self.user_id = user_id
        self._cached: tuple[float, list[dict[str, Any]]] | None = None

    def available(self) -> bool:
        return bool(self._client or self._key)

    def _sdk(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._key:
            raise AccountsUnavailableError(
                "No Composio API key. Set COMPOSIO_API_KEY in the environment."
            )
        try:
            import composio
        except ImportError as exc:
            raise AccountsUnavailableError("The Composio SDK is not installed.") from exc
        self._client = composio.Composio(api_key=self._key)
        return self._client

    # -- connections --------------------------------------------------------

    def connections(self) -> list[dict[str, Any]]:
        """One row per toolkit, preferring a live connection over a dead one."""
        client = self._sdk()
        try:
            result = client.connected_accounts.list(user_ids=[self.user_id], limit=100)
        except Exception as exc:
            _reraise(exc)
            raise  # unreachable; _reraise always raises

        best: dict[str, dict[str, Any]] = {}
        for item in list(getattr(result, "items", None) or []):
            slug = getattr(getattr(item, "toolkit", None), "slug", None)
            if not slug:
                continue
            status = str(getattr(item, "status", "unknown"))
            row = {
                "toolkit": slug,
                "status": status,
                "connected": status.lower() in LIVE_STATUSES,
                "needs_reconnect": status.lower() in DEAD_STATUSES,
            }
            # A toolkit can hold several connections; a working one wins.
            if slug not in best or (row["connected"] and not best[slug]["connected"]):
                best[slug] = row
        return sorted(best.values(), key=lambda row: row["toolkit"])

    def cached_connections(self) -> list[dict[str, Any]]:
        """For status polling. A reconnect shows up within the cache window."""
        now = time.monotonic()
        if self._cached is None or now - self._cached[0] >= CONNECTIONS_CACHE_SECONDS:
            self._cached = (now, self.connections())
        return self._cached[1]

    def invalidate(self) -> None:
        self._cached = None

    def require_connected(self, toolkit: str) -> None:
        for row in self.connections():
            if row["toolkit"] == toolkit:
                if row["connected"]:
                    return
                raise AccountAuthError(
                    f"The {toolkit} connection is {row['status'].lower()}. "
                    f"Reconnect it in Composio; Marvi OS cannot run the OAuth flow."
                )
        raise AccountAuthError(f"No {toolkit} account is connected.")

    # -- actions ------------------------------------------------------------

    def execute(self, action: str, arguments: dict[str, Any] | None = None) -> Any:
        client = self._sdk()
        try:
            result = client.tools.execute(
                slug=action,
                arguments=arguments or {},
                user_id=self.user_id,
                dangerously_skip_version_check=True,
            )
        except TypeError as exc:
            # Older SDKs lack the version-check opt-out.
            if "dangerously_skip_version_check" not in str(exc):
                _reraise(exc)
            result = client.tools.execute(
                slug=action, arguments=arguments or {}, user_id=self.user_id
            )
        except Exception as exc:
            _reraise(exc)
            raise  # unreachable

        payload = _as_dict(result)
        if isinstance(payload, dict) and payload.get("successful") is False:
            raise AccountTransientError(str(payload.get("error") or f"{action} failed"))
        return payload


def register_account_tools(registry, accounts: ComposioAccounts) -> None:
    """A deliberately small account surface. Reads are enveloped; writes are
    sensitive, external, and therefore confirmed and deduplicated."""
    from .tools import ToolSpec

    def accounts_status() -> dict[str, Any]:
        rows = accounts.connections()
        return {
            "connected": [r["toolkit"] for r in rows if r["connected"]],
            "needs_reconnect": [r["toolkit"] for r in rows if r["needs_reconnect"]],
            "accounts": rows,
        }

    def email_recent(limit: int = 5) -> dict[str, Any]:
        accounts.require_connected("gmail")
        payload = accounts.execute(
            GMAIL_FETCH, {"max_results": max(1, min(limit, 25)), "verbose": False}
        )
        return wrap_external("composio:gmail", payload).model_dump()

    def calendar_events(limit: int = 10) -> dict[str, Any]:
        accounts.require_connected("googlecalendar")
        payload = accounts.execute(
            CALENDAR_EVENTS,
            {"calendarId": "primary", "maxResults": max(1, min(limit, 25)), "singleEvents": True},
        )
        return wrap_external("composio:googlecalendar", payload).model_dump()

    def send_email(recipient_email: str, subject: str, body: str) -> Any:
        accounts.require_connected("gmail")
        return accounts.execute(
            GMAIL_SEND,
            {"recipient_email": recipient_email, "subject": subject, "body": body},
        )

    registry.register(
        ToolSpec(
            name="accounts_status",
            description="Read which connected accounts are available",
            arguments={},
            sensitive=False,
            handler=accounts_status,
        )
    )
    registry.register(
        ToolSpec(
            name="email_recent",
            description="Read recent email",
            arguments={},
            optional={"limit": int},
            sensitive=False,
            handler=email_recent,
        )
    )
    registry.register(
        ToolSpec(
            name="calendar_events",
            description="Read upcoming calendar events",
            arguments={},
            optional={"limit": int},
            sensitive=False,
            handler=calendar_events,
        )
    )
    registry.register(
        ToolSpec(
            name="send_email",
            description="Send an email",
            arguments={"recipient_email": str, "subject": str, "body": str},
            sensitive=True,
            external=True,
            handler=send_email,
        )
    )
