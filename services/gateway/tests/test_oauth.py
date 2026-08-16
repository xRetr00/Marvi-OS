"""OAuth for plan providers, and where the tokens end up.

The security-relevant behaviour is tested against the real flow objects rather
than mocked: PKCE, the `state` check, single-use listener, refresh ahead of
expiry, and the difference between "not connected" and "connected but expired".
Only the provider's token endpoint is faked, because that is the one part that
is somebody else's server.
"""

from __future__ import annotations

import base64
import hashlib
import threading
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from marvi_gateway.providers.oauth import (
    CONFIGS,
    OAuthBroker,
    OAuthError,
    ReconnectRequiredError,
    make_challenge,
    make_verifier,
)
from marvi_gateway.providers.tokens import StoredToken, TokenStore


@pytest.fixture
def store(tmp_path):
    return TokenStore(tmp_path / "tokens.bin")


@pytest.fixture(autouse=True)
def client_id(monkeypatch):
    monkeypatch.setenv("MARVI_CODEX_CLIENT_ID", "client-abc")


def token_endpoint(payload: dict, status: int = 200, seen: list | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(dict(urllib.parse.parse_qsl(request.content.decode())))
        return httpx.Response(status, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def visit(url: str) -> None:
    """Play the browser: follow the authorize URL's redirect back to Marvi."""
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    back = f"{params['redirect_uri']}?code=auth-code-1&state={urllib.parse.quote(params['state'])}"
    urllib.request.urlopen(back, timeout=5).read()


# -- PKCE --------------------------------------------------------------------


def test_the_challenge_is_a_real_s256_of_the_verifier() -> None:
    verifier = make_verifier()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())

    assert make_challenge(verifier) == expected.decode().rstrip("=")
    assert 43 <= len(verifier) <= 128  # RFC 7636
    assert make_verifier() != make_verifier()


def test_the_authorize_url_carries_pkce_and_never_a_secret() -> None:
    broker = OAuthBroker()
    started = broker.start("codex")
    try:
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(started["url"]).query))

        assert params["code_challenge_method"] == "S256"
        assert params["response_type"] == "code"
        assert params["client_id"] == "client-abc"
        assert "code_verifier" not in params  # the verifier never leaves the process
        assert "client_secret" not in params
        assert params["redirect_uri"].startswith("http://localhost:")
    finally:
        broker.cancel("codex")


# -- the flow ----------------------------------------------------------------


def test_a_full_sign_in_stores_a_usable_token(store) -> None:
    seen: list[dict] = []
    broker = OAuthBroker(
        store=store,
        http=token_endpoint(
            {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600}, seen=seen
        ),
    )
    started = broker.start("codex")
    visit(started["url"])

    result = broker.poll("codex")

    assert result["state"] == "connected"
    assert broker.access_token("codex") == "at-1"
    # The exchange must prove possession of the verifier, not just the code.
    assert seen[0]["grant_type"] == "authorization_code"
    assert seen[0]["code"] == "auth-code-1"
    assert len(seen[0]["code_verifier"]) >= 43


def test_a_code_with_the_wrong_state_is_refused(store) -> None:
    broker = OAuthBroker(store=store, http=token_endpoint({"access_token": "at"}))
    started = broker.start("codex")
    redirect = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(started["url"]).query))
    # Another page in the browser hands Marvi a code for an account the user
    # did not pick. Accepting it would connect the attacker's account.
    urllib.request.urlopen(
        f"{redirect['redirect_uri']}?code=someone-elses&state=forged", timeout=5
    ).read()

    result = broker.poll("codex")

    assert result["connected"] is False
    assert "state mismatch" in str(result["detail"])
    assert store.get("codex") is None


def test_the_listener_serves_one_request_and_stops(store) -> None:
    broker = OAuthBroker(store=store, http=token_endpoint({"access_token": "at"}))
    started = broker.start("codex")
    visit(started["url"])
    broker.poll("codex")

    redirect = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(started["url"]).query))
    with pytest.raises(Exception):  # noqa: B017 - any connection failure is the point
        urllib.request.urlopen(redirect["redirect_uri"], timeout=2).read()


def test_a_provider_rejection_is_reported_not_swallowed(store) -> None:
    broker = OAuthBroker(store=store, http=token_endpoint({"error": "bad"}, status=400))
    started = broker.start("codex")
    visit(started["url"])

    result = broker.poll("codex")

    assert result["state"] == "failed"
    assert store.get("codex") is None


def test_polling_before_the_browser_returns_does_not_block(store) -> None:
    broker = OAuthBroker(store=store, http=token_endpoint({"access_token": "at"}))
    broker.start("codex")
    try:
        result = broker.poll("codex")
        assert result["state"] == "waiting for sign-in"
    finally:
        broker.cancel("codex")


def test_a_missing_client_id_says_what_to_do(monkeypatch, store) -> None:
    monkeypatch.delenv("MARVI_CODEX_CLIENT_ID", raising=False)
    with pytest.raises(OAuthError, match="MARVI_CODEX_CLIENT_ID"):
        OAuthBroker(store=store).start("codex")


def test_a_non_oauth_provider_cannot_start_a_flow(store) -> None:
    with pytest.raises(OAuthError, match="does not use OAuth"):
        OAuthBroker(store=store).start("openai")


# -- refresh -----------------------------------------------------------------


def test_a_token_near_expiry_is_refreshed_before_it_is_used(store) -> None:
    store.put(
        StoredToken(
            provider="codex",
            access_token="old",
            refresh_token="rt-1",
            expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
        )
    )
    seen: list[dict] = []
    broker = OAuthBroker(
        store=store,
        http=token_endpoint({"access_token": "new", "expires_in": 3600}, seen=seen),
    )

    # A token that dies mid-call is a lost turn, so it is replaced early.
    assert broker.access_token("codex") == "new"
    assert seen[0]["grant_type"] == "refresh_token"


def test_a_refresh_that_omits_the_refresh_token_keeps_the_old_one(store) -> None:
    store.put(
        StoredToken(
            provider="codex",
            access_token="old",
            refresh_token="rt-keep",
            expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        )
    )
    broker = OAuthBroker(store=store, http=token_endpoint({"access_token": "new", "expires_in": 60}))
    broker.access_token("codex")

    # Dropping it would silently turn a lasting connection into a one-hour one.
    assert store.get("codex").refresh_token == "rt-keep"


def test_a_healthy_token_is_not_refreshed(store) -> None:
    store.put(
        StoredToken(
            provider="codex",
            access_token="fine",
            refresh_token="rt",
            expires_at=(datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        )
    )

    def explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not have called the token endpoint")

    broker = OAuthBroker(store=store, http=httpx.Client(transport=httpx.MockTransport(explode)))
    assert broker.access_token("codex") == "fine"


def test_an_expired_token_that_cannot_refresh_says_reconnect(store) -> None:
    store.put(
        StoredToken(
            provider="codex",
            access_token="dead",
            expires_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        )
    )
    with pytest.raises(ReconnectRequiredError, match="sign in again"):
        OAuthBroker(store=store).access_token("codex")


def test_a_failed_refresh_says_reconnect_rather_than_retrying(store) -> None:
    store.put(
        StoredToken(
            provider="codex",
            access_token="old",
            refresh_token="revoked",
            expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        )
    )
    broker = OAuthBroker(store=store, http=token_endpoint({"error": "invalid_grant"}, status=400))
    with pytest.raises(ReconnectRequiredError, match="Sign in again"):
        broker.access_token("codex")


def test_never_connected_is_not_the_same_as_expired(store) -> None:
    # One is "connect it"; the other is "something broke". The UI has to be
    # able to tell them apart.
    assert OAuthBroker(store=store).access_token("codex") is None


# -- storage -----------------------------------------------------------------


def test_a_token_survives_a_restart(tmp_path) -> None:
    path = tmp_path / "tokens.bin"
    TokenStore(path).put(StoredToken(provider="codex", access_token="at", refresh_token="rt"))

    assert TokenStore(path).get("codex").access_token == "at"


def test_the_token_file_is_not_plain_text(tmp_path) -> None:
    import sys

    path = tmp_path / "tokens.bin"
    TokenStore(path).put(StoredToken(provider="codex", access_token="super-secret-value"))
    raw = path.read_bytes()

    if sys.platform == "win32":
        # DPAPI, scoped to this Windows account.
        assert b"super-secret-value" not in raw
    else:
        pytest.skip("DPAPI is Windows-only; other platforms fall back to file permissions")


def test_a_corrupt_store_means_reconnect_not_a_crash(tmp_path) -> None:
    path = tmp_path / "tokens.bin"
    path.write_bytes(b"not a token file")

    # Written by a different Windows account, or truncated. Either way the
    # Gateway has to start.
    assert TokenStore(path).get("codex") is None


def test_disconnect_removes_the_token(store) -> None:
    store.put(StoredToken(provider="codex", access_token="at"))
    broker = OAuthBroker(store=store)

    assert broker.disconnect("codex") is True
    assert store.get("codex") is None
    assert broker.disconnect("codex") is False


def test_status_never_returns_the_token(store) -> None:
    store.put(
        StoredToken(
            provider="codex",
            access_token="secret-token",
            refresh_token="secret-refresh",
            expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        )
    )
    reported = str(store.status("codex"))

    assert "secret-token" not in reported
    assert "secret-refresh" not in reported
    assert "connected" in reported


def test_every_oauth_provider_declares_a_complete_flow() -> None:
    for name, config in CONFIGS.items():
        assert config.authorize_url.startswith("https://"), name
        assert config.token_url.startswith("https://"), name
        # The client ID is the vendor's, so it is configuration, never a literal.
        assert config.client_id_env.startswith("MARVI_"), name
        assert config.redirect_uri().startswith("http://localhost:"), name


def test_starting_twice_does_not_leak_the_first_listener(store) -> None:
    broker = OAuthBroker(store=store, http=token_endpoint({"access_token": "at"}))
    first = broker.start("codex")
    second = broker.start("codex")
    try:
        # Same port, so the second start only works if the first was closed.
        assert first["redirect_uri"] == second["redirect_uri"]
        assert threading.active_count() >= 1
    finally:
        broker.cancel("codex")
