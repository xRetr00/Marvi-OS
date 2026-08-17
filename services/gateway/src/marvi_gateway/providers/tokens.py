"""Where OAuth tokens live.

A refresh token is a long-lived credential: anyone holding it can mint access
tokens against the user's account until it is revoked. The phase document left
this as an open decision rather than defaulting to a JSON file, so here is the
decision.

**Windows: DPAPI, scoped to the user.** `CryptProtectData` encrypts with a key
derived from the logged-in Windows account. The file on disk is useless to
another account on the same machine and useless if copied elsewhere, and it
needs no password prompt, no keyring service, and no new dependency — it is a
`ctypes` call into `crypt32`.

**Elsewhere: a file with owner-only permissions**, and Marvi says so rather than
pretending it is encrypted. Marvi is Windows-first; this path exists so tests
and development on other platforms work, not as an equivalent guarantee.

What is deliberately *not* here: the tokens never go into `providers.env`
alongside the API keys. That file is written and read by the settings GUI, and a
refresh token is not a setting.
"""

from __future__ import annotations

import contextlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Refresh this far before expiry. A token that expires mid-call is a failed
# turn, and the clock on the token is not necessarily the clock here.
REFRESH_MARGIN_SECONDS = 120


@dataclass
class StoredToken:
    provider: str
    access_token: str
    refresh_token: str = ""
    expires_at: str = ""  # ISO 8601, empty when the provider gave no expiry
    scope: str = ""
    account: str = ""

    def expiry(self) -> datetime | None:
        if not self.expires_at:
            return None
        try:
            return datetime.fromisoformat(self.expires_at)
        except ValueError:
            return None

    def stale(self, now: datetime | None = None) -> bool:
        """True when this token should be refreshed before the next call."""
        expiry = self.expiry()
        if expiry is None:
            return False
        moment = now or datetime.now(UTC)
        return expiry - moment <= timedelta(seconds=REFRESH_MARGIN_SECONDS)

    def dead(self, now: datetime | None = None) -> bool:
        """Past expiry with no way back — the UI should say 'reconnect'."""
        expiry = self.expiry()
        if expiry is None:
            return False
        return expiry <= (now or datetime.now(UTC)) and not self.refresh_token


def token_path() -> Path:
    from ..paths import token_store

    return token_store()


# -- Windows DPAPI -----------------------------------------------------------


def _dpapi_available() -> bool:
    return sys.platform == "win32"


def _dpapi(encrypt: bool, data: bytes) -> bytes:
    """Call CryptProtectData / CryptUnprotectData. Windows only."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    source = Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    result = Blob()
    function = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    # CRYPTPROTECT_UI_FORBIDDEN (0x1): never prompt. This runs in a background
    # service; a modal dialog nobody sees would hang the Gateway.
    ok = function(
        ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(result)
    )
    if not ok:
        raise OSError(f"DPAPI {'encrypt' if encrypt else 'decrypt'} failed")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


class TokenStore:
    """Reads and writes the token file. One instance is enough."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or token_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def encrypted(self) -> bool:
        return _dpapi_available()

    def _load(self) -> dict[str, dict[str, str]]:
        try:
            raw = self.path.read_bytes()
        except OSError:
            return {}
        if not raw:
            return {}
        try:
            plain = _dpapi(False, raw) if _dpapi_available() else raw
            return json.loads(plain.decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            # A file written under a different Windows account cannot be read
            # here, and neither can a corrupt one. Both mean "reconnect", not
            # "crash on startup".
            return {}

    def _save(self, everything: dict[str, dict[str, str]]) -> None:
        plain = json.dumps(everything).encode("utf-8")
        self.path.write_bytes(_dpapi(True, plain) if _dpapi_available() else plain)
        if not _dpapi_available():
            with contextlib.suppress(OSError):
                self.path.chmod(0o600)

    def get(self, provider: str) -> StoredToken | None:
        row = self._load().get(provider)
        return StoredToken(**row) if row else None

    def put(self, token: StoredToken) -> None:
        everything = self._load()
        everything[token.provider] = asdict(token)
        self._save(everything)

    def forget(self, provider: str) -> bool:
        everything = self._load()
        if provider not in everything:
            return False
        del everything[provider]
        self._save(everything)
        return True

    def providers(self) -> list[str]:
        return sorted(self._load())

    def status(self, provider: str) -> dict[str, object]:
        """What the page needs, without ever returning the token itself."""
        token = self.get(provider)
        if token is None:
            return {"connected": False, "state": "not connected"}
        if token.dead():
            return {"connected": False, "state": "expired — reconnect", "account": token.account}
        return {
            "connected": True,
            "state": "connected",
            "account": token.account,
            "expires_at": token.expires_at,
            "refreshable": bool(token.refresh_token),
            "encrypted_at_rest": self.encrypted,
        }
