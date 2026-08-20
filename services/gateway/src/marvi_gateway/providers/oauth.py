"""OAuth for plan providers — authorization code with PKCE.

Marvi never sees a provider password. The user signs in on the provider's own
page in their own browser; Marvi only receives the redirect. That is not a
nicety, it is the reason this is a browser flow at all rather than a form.

The shape, and why each part is here:

* **PKCE, always.** The redirect lands on `http://localhost:<port>`, which any
  local process could race for. The verifier never leaves this process, so a
  stolen authorization code is worth nothing on its own.
* **`state` is checked, not just sent.** Without that, another page in the
  user's browser can hand Marvi a code for an account the user did not choose.
* **One request, then the server dies.** The loopback listener answers exactly
  one callback and shuts down; a listener left running is a way in.
* **Refresh happens ahead of expiry**, not on failure. A token that dies
  mid-call is a lost turn, and on the voice path that is a visible stall.

Client IDs are **not** hardcoded. Each provider's is read from the environment,
because these are the vendor's own published client identifiers rather than
something Marvi owns — baking in a value that a vendor rotates would fail
silently months later. `docs/PROVIDERS.md` says which variable to set.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import logging
import os
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from .base import ProviderProfile, get, set_token_hook
from .tokens import StoredToken, TokenStore

logger = logging.getLogger(__name__)

CALLBACK_TIMEOUT_SECONDS = 300.0
TOKEN_REQUEST_TIMEOUT = 30.0


class OAuthError(Exception):
    """The flow could not be completed."""


class ReconnectRequiredError(OAuthError):
    """The stored token is dead and only the user can fix it."""


@dataclass(frozen=True)
class OAuthConfig:
    """What a provider's OAuth flow needs. All of it resolves from config."""

    authorize_url: str
    token_url: str
    client_id_env: str
    scopes: tuple[str, ...] = ()
    # Must match a redirect URI the vendor has registered for that client.
    redirect_port: int = 1455
    redirect_path: str = "/auth/callback"
    extra_authorize_params: dict[str, str] = field(default_factory=dict)

    def client_id(self) -> str:
        return os.environ.get(self.client_id_env, "").strip()

    def redirect_uri(self) -> str:
        return f"http://localhost:{self.redirect_port}{self.redirect_path}"


# Which provider uses which flow. Kept beside the flow rather than on the
# profile so `base.py` stays free of OAuth concerns.
CONFIGS: dict[str, OAuthConfig] = {
    "codex": OAuthConfig(
        authorize_url="https://auth.openai.com/oauth/authorize",
        token_url="https://auth.openai.com/oauth/token",
        client_id_env="MARVI_CODEX_CLIENT_ID",
        scopes=("openid", "profile", "email", "offline_access"),
        redirect_port=1455,
    ),
    "claude-code": OAuthConfig(
        authorize_url="https://claude.ai/oauth/authorize",
        token_url="https://console.anthropic.com/v1/oauth/token",
        client_id_env="MARVI_CLAUDE_CODE_CLIENT_ID",
        scopes=("org:create_api_key", "user:profile", "user:inference"),
        redirect_port=54545,
    ),
}


def config_for(name: str) -> OAuthConfig | None:
    return CONFIGS.get(name)


# -- PKCE --------------------------------------------------------------------


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def make_verifier() -> str:
    """43 to 128 characters of the unreserved charset, per RFC 7636."""
    return _b64url(secrets.token_bytes(32))


def make_challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


# -- the loopback listener ---------------------------------------------------


class _Callback:
    """Holds the single result the browser redirect delivers."""

    def __init__(self) -> None:
        self.code = ""
        self.state = ""
        self.error = ""
        self.done = threading.Event()


def _handler_for(result: _Callback, expected_state: str, path: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != path:
                self.send_response(404)
                self.end_headers()
                return
            query = urllib.parse.parse_qs(parsed.query)
            state = (query.get("state") or [""])[0]
            if not secrets.compare_digest(state, expected_state):
                # A code arriving with the wrong state is not this flow. Taking
                # it would connect whatever account that other page chose.
                result.error = "state mismatch — the sign-in did not come from Marvi"
            elif query.get("error"):
                result.error = (query.get("error_description") or query["error"])[0]
            else:
                result.code = (query.get("code") or [""])[0]
                if not result.code:
                    result.error = "no authorization code in the redirect"

            # Recorded before the response goes out, not after. The browser
            # reaching "Connected." has to mean Marvi already has the code --
            # the other order let the client finish reading while this thread
            # was still descheduled, so a poll straight afterwards answered
            # "waiting for sign-in" for a sign-in that had already arrived.
            result.done.set()

            body = (
                b"<html><body style='font-family:sans-serif;padding:3rem'>"
                + (
                    b"<h2>Connected.</h2><p>You can close this tab and go back to Marvi.</p>"
                    if not result.error
                    else b"<h2>Sign-in failed.</h2><p>Go back to Marvi and try again.</p>"
                )
                + b"</body></html>"
            )
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: Any) -> None:
            """Silence the default stderr access log."""

    return Handler


class _CallbackServer(HTTPServer):
    """The redirect listener, on a port the vendor pins.

    `allow_reuse_address` is off, and that is the whole point of the subclass.
    `HTTPServer` turns it on, which on Windows does not mean what it means on
    Unix: there, SO_REUSEADDR lets a bind succeed even when another socket is
    *actively listening* on the same port, and which of the two a connection
    reaches is not defined. A leftover listener from an abandoned flow would
    therefore not collide loudly -- it would quietly swallow the next sign-in,
    which then hung until the browser gave up.

    Off, a conflict raises OSError at bind, and `start` already turns that into
    "Port ... is busy", which is both true and actionable.
    """

    allow_reuse_address = False


# -- the flow ----------------------------------------------------------------


@dataclass
class PendingFlow:
    provider: str
    verifier: str
    state: str
    url: str
    started: float
    result: _Callback
    server: HTTPServer


class OAuthBroker:
    """Runs sign-in flows and keeps access tokens fresh.

    One instance lives on the Gateway. `access_token` is what the rest of the
    system calls; everything else exists to keep that method able to answer.
    """

    def __init__(self, store: TokenStore | None = None, http: Any = None) -> None:
        self.store = store or TokenStore()
        self.http = http
        self._pending: dict[str, PendingFlow] = {}
        self._lock = threading.Lock()

    # -- starting ------------------------------------------------------------

    def start(self, name: str) -> dict[str, str]:
        """Open a flow and return the URL the user must visit.

        Marvi does not open the browser from here — the caller does, so the
        click stays connected to a user action.
        """
        profile = get(name)
        config = config_for(profile.name)
        if config is None:
            raise OAuthError(f"{profile.name} does not use OAuth")
        client_id = config.client_id()
        if not client_id:
            raise OAuthError(
                f"{profile.label()} needs its client ID in {config.client_id_env}. "
                "See docs/PROVIDERS.md — Marvi does not ship vendor client IDs."
            )

        self.cancel(profile.name)
        verifier = make_verifier()
        state = _b64url(secrets.token_bytes(16))
        result = _Callback()
        try:
            server = _CallbackServer(
                ("127.0.0.1", config.redirect_port),
                _handler_for(result, state, config.redirect_path),
            )
        except OSError as exc:
            raise OAuthError(
                f"Port {config.redirect_port} is busy, and the vendor only accepts "
                f"that port for this client: {exc}"
            ) from exc

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": config.redirect_uri(),
            "state": state,
            "code_challenge": make_challenge(verifier),
            "code_challenge_method": "S256",
            **config.extra_authorize_params,
        }
        if config.scopes:
            params["scope"] = " ".join(config.scopes)
        url = f"{config.authorize_url}?{urllib.parse.urlencode(params)}"

        def serve_once() -> None:
            # The socket is released as soon as its one request is served,
            # rather than waiting for `poll` or `cancel` to come and close it.
            # Nothing guarantees either is ever called -- an abandoned flow
            # leaves the listener up -- and on a pinned port a stray listener
            # is the next sign-in's problem, not this one's.
            try:
                server.handle_request()
            finally:
                with contextlib.suppress(OSError):
                    server.server_close()

        thread = threading.Thread(target=serve_once, daemon=True)
        thread.start()
        with self._lock:
            self._pending[profile.name] = PendingFlow(
                provider=profile.name,
                verifier=verifier,
                state=state,
                url=url,
                started=time.monotonic(),
                result=result,
                server=server,
            )
        return {"url": url, "redirect_uri": config.redirect_uri()}

    def cancel(self, name: str) -> None:
        with self._lock:
            flow = self._pending.pop(name, None)
        if flow is not None:
            with contextlib.suppress(OSError):
                flow.server.server_close()

    def pending(self, name: str) -> bool:
        with self._lock:
            return name in self._pending

    # -- completing ----------------------------------------------------------

    def poll(self, name: str) -> dict[str, object]:
        """Has the browser come back yet? Never blocks."""
        with self._lock:
            flow = self._pending.get(name)
        if flow is None:
            return {"state": "idle", **self.store.status(name)}
        if not flow.result.done.is_set():
            if time.monotonic() - flow.started > CALLBACK_TIMEOUT_SECONDS:
                self.cancel(name)
                return {"state": "timed out", "connected": False}
            return {"state": "waiting for sign-in", "connected": False, "url": flow.url}

        self.cancel(name)
        if flow.result.error:
            return {"state": "failed", "connected": False, "detail": flow.result.error}
        try:
            token = self._exchange(name, flow.verifier, flow.result.code)
        except OAuthError as exc:
            return {"state": "failed", "connected": False, "detail": str(exc)}
        self.store.put(token)
        return {"state": "connected", **self.store.status(name)}

    def _post_token(self, config: OAuthConfig, data: dict[str, str]) -> dict[str, Any]:
        import httpx

        client = self.http or httpx.Client(timeout=TOKEN_REQUEST_TIMEOUT)
        try:
            response = client.post(
                config.token_url,
                data=data,
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            if response.status_code >= 400:
                raise OAuthError(
                    f"the provider rejected the token request ({response.status_code})"
                )
            return response.json()
        except OAuthError:
            raise
        except Exception as exc:
            raise OAuthError(f"could not reach the token endpoint: {exc}") from exc
        finally:
            if self.http is None:
                client.close()

    @staticmethod
    def _to_token(name: str, payload: dict[str, Any], previous: StoredToken | None) -> StoredToken:
        access = str(payload.get("access_token") or "")
        if not access:
            raise OAuthError("the provider returned no access token")
        expires_in = payload.get("expires_in")
        expires_at = ""
        if isinstance(expires_in, int | float) and expires_in > 0:
            expires_at = (datetime.now(UTC) + timedelta(seconds=float(expires_in))).isoformat()
        # Registered before it is stored or logged: an access token is a
        # credential that never went through the environment, so the redactor
        # has no other way to learn it.
        from ..logs import redactor

        redactor().add(access)
        refresh = str(payload.get("refresh_token") or "")
        if refresh:
            redactor().add(refresh)
        return StoredToken(
            provider=name,
            access_token=access,
            # A refresh response often omits the refresh token, meaning "keep
            # the one you have". Dropping it here would silently turn a
            # long-lived connection into a one-hour one.
            refresh_token=str(payload.get("refresh_token") or (previous.refresh_token if previous else "")),
            expires_at=expires_at,
            scope=str(payload.get("scope") or ""),
            account=str(payload.get("account_id") or (previous.account if previous else "")),
        )

    def _exchange(self, name: str, verifier: str, code: str) -> StoredToken:
        config = config_for(name)
        assert config is not None  # only reachable for OAuth providers
        payload = self._post_token(
            config,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.redirect_uri(),
                "client_id": config.client_id(),
                "code_verifier": verifier,
            },
        )
        return self._to_token(name, payload, None)

    # -- using ---------------------------------------------------------------

    def refresh(self, name: str) -> StoredToken:
        config = config_for(name)
        current = self.store.get(name)
        if config is None or current is None:
            raise ReconnectRequiredError(f"{name} is not connected")
        if not current.refresh_token:
            raise ReconnectRequiredError(f"{name} cannot be refreshed; sign in again")
        payload = self._post_token(
            config,
            {
                "grant_type": "refresh_token",
                "refresh_token": current.refresh_token,
                "client_id": config.client_id(),
            },
        )
        token = self._to_token(name, payload, current)
        self.store.put(token)
        logger.info("refreshed the %s token", name)
        return token

    def access_token(self, name: str) -> str | None:
        """A usable access token, refreshed if it is about to expire.

        Returns None when the provider is simply not connected. Raises when it
        *was* connected and can no longer be recovered, because those are
        different things to the user: one is "connect it", the other is
        "something broke, reconnect".
        """
        token = self.store.get(name)
        if token is None:
            return None
        if not token.stale():
            return token.access_token
        if not token.refresh_token:
            raise ReconnectRequiredError(f"the {name} session expired; sign in again")
        try:
            return self.refresh(name).access_token
        except OAuthError as exc:
            raise ReconnectRequiredError(
                f"could not refresh {name}: {exc}. Sign in again."
            ) from exc

    def disconnect(self, name: str) -> bool:
        self.cancel(name)
        return self.store.forget(name)

    def status(self, profile: ProviderProfile) -> dict[str, object] | None:
        """OAuth state for the providers page; None for non-OAuth providers."""
        if config_for(profile.name) is None:
            return None
        config = CONFIGS[profile.name]
        state: dict[str, object] = dict(self.store.status(profile.name))
        state["client_id_env"] = config.client_id_env
        state["client_id_set"] = bool(config.client_id())
        if self.pending(profile.name):
            state["state"] = "waiting for sign-in"
        return state


# -- the process-wide broker -------------------------------------------------

_broker: OAuthBroker | None = None


def broker() -> OAuthBroker:
    """The one broker. Created on first use so importing costs nothing."""
    global _broker
    if _broker is None:
        _broker = OAuthBroker()
    return _broker


def _hook(name: str) -> str | None:
    """Resolve a provider's access token, or nothing if it uses no OAuth.

    A dead session returns None rather than raising: `configured()` asks this
    on every page render, and a page must not blow up because a token lapsed.
    The reconnect state is reported separately.
    """
    if config_for(name) is None:
        return None
    try:
        return broker().access_token(name)
    except OAuthError:
        return None


set_token_hook(_hook)
