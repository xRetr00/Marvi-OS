from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[4]


class ComponentStatus(BaseModel):
    state: str
    detail: str


class GatewayStatus(BaseModel):
    product: str
    version: str
    state: str
    components: dict[str, ComponentStatus]


def read_version(root: Path = REPO_ROOT) -> str:
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def create_app(version: str | None = None) -> FastAPI:
    product_version = version or read_version()
    app = FastAPI(title="Marvi Gateway", version=product_version, docs_url=None, redoc_url=None)

    @app.get("/health", response_model=GatewayStatus)
    async def health() -> GatewayStatus:
        return GatewayStatus(
            product="Marvi OS",
            version=product_version,
            state="starting",
            components={
                "gateway": ComponentStatus(state="ready", detail="local facade online"),
                "livekit": ComponentStatus(state="pending", detail="server binary not pinned"),
                "voice": ComponentStatus(state="pending", detail="native model bakeoff required"),
            },
        )

    return app


app = create_app()
