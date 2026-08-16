from __future__ import annotations

import os
import socket
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from livekit import api
from pydantic import BaseModel

from .runtime import (
    ComponentStatus,
    ConfirmationDecision,
    ModeUpdate,
    RuntimeStatus,
    RuntimeStore,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


class LiveKitConnection(BaseModel):
    url: str
    room: str
    token: str


def livekit_is_ready(host: str = "127.0.0.1", port: int = 7880) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.05):
            return True
    except OSError:
        return False


def read_version(root: Path = REPO_ROOT) -> str:
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def create_app(version: str | None = None, runtime: RuntimeStore | None = None) -> FastAPI:
    product_version = version or read_version()
    runtime_store = runtime or RuntimeStore()
    app = FastAPI(title="Marvi Gateway", version=product_version, docs_url=None, redoc_url=None)

    def current_status() -> RuntimeStatus:
        livekit_ready = livekit_is_ready()
        return RuntimeStatus(
            product="Marvi OS",
            version=product_version,
            state="starting",
            components={
                "gateway": ComponentStatus(state="ready", detail="local facade online"),
                "livekit": ComponentStatus(
                    state="ready" if livekit_ready else "pending",
                    detail="local server online" if livekit_ready else "local server not running",
                ),
                "voice": ComponentStatus(state="starting", detail="native streaming worker available"),
                "vision": ComponentStatus(state="pending", detail="local model not selected"),
                "room": ComponentStatus(state="offline", detail="sidecar not connected"),
            },
            assistant=runtime_store.assistant,
        )

    @app.get("/health", response_model=RuntimeStatus)
    async def health() -> RuntimeStatus:
        return current_status()

    @app.get("/runtime", response_model=RuntimeStatus)
    async def runtime_status() -> RuntimeStatus:
        return current_status()

    @app.post("/livekit/session", response_model=LiveKitConnection)
    async def livekit_session() -> LiveKitConnection:
        url = os.environ.get("LIVEKIT_URL", "ws://127.0.0.1:7880")
        key = os.environ.get("LIVEKIT_API_KEY", "devkey")
        secret = os.environ.get("LIVEKIT_API_SECRET", "secret")
        room = os.environ.get("MARVI_LIVEKIT_ROOM", "marvi-os-local")
        identity = f"marvi-desktop-{uuid4().hex[:10]}"
        token = (
            api.AccessToken(key, secret)
            .with_identity(identity)
            .with_name("Marvi OS Desktop")
            .with_grants(
                api.VideoGrants(
                    room_join=True, room=room, can_publish=True, can_subscribe=True
                )
            )
            .to_jwt()
        )
        return LiveKitConnection(url=url, room=room, token=token)

    @app.put("/runtime/mode", response_model=RuntimeStatus)
    async def set_mode(update: ModeUpdate) -> RuntimeStatus:
        runtime_store.set_yolo(update.yolo)
        return current_status()

    @app.post("/confirmations/{token}", response_model=RuntimeStatus)
    async def resolve_confirmation(
        token: str, decision: ConfirmationDecision
    ) -> RuntimeStatus:
        if runtime_store.resolve_confirmation(token, decision.decision) is None:
            raise HTTPException(status_code=404, detail="confirmation not found")
        return current_status()

    return app


app = create_app()
