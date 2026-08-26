"""Marvi-owned administrative API for messaging sender pairing."""

from __future__ import annotations

from typing import Any

from ._vendor import activate


def list_pending() -> list[dict[str, Any]]:
    activate(managed=False)
    from gateway.pairing import PairingStore
    return list(PairingStore().list_pending())


def approve(platform: str, credential: str) -> dict[str, Any] | None:
    activate(managed=False)
    from gateway.pairing import PairingStore

    store = PairingStore()
    credential = credential.strip()
    if store.looks_like_request_id(credential):
        return store.approve_request(platform.strip().lower(), credential)
    return store.approve_code(platform.strip().lower(), credential.upper())
