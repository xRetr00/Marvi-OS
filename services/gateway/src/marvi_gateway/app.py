from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException

from .runtime import (
    ComponentStatus,
    ConfirmationDecision,
    ModeUpdate,
    RuntimeStatus,
    RuntimeStore,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def read_version(root: Path = REPO_ROOT) -> str:
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def create_app(version: str | None = None, runtime: RuntimeStore | None = None) -> FastAPI:
    product_version = version or read_version()
    runtime_store = runtime or RuntimeStore()
    app = FastAPI(title="Marvi Gateway", version=product_version, docs_url=None, redoc_url=None)

    def current_status() -> RuntimeStatus:
        return RuntimeStatus(
            product="Marvi OS",
            version=product_version,
            state="starting",
            components={
                "gateway": ComponentStatus(state="ready", detail="local facade online"),
                "livekit": ComponentStatus(state="pending", detail="server binary not pinned"),
                "voice": ComponentStatus(state="pending", detail="native model bakeoff required"),
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
