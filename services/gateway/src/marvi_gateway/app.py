from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from livekit import api
from pydantic import BaseModel, Field

from .room import RoomSidecar, register_room_tools
from .runtime import (
    ArgumentsMutatedError,
    AuditPage,
    ComponentStatus,
    ConfirmationDecision,
    ModeUpdate,
    RuntimeStatus,
    RuntimeStore,
    TokenRejectedError,
)
from .tools import InvalidArgumentsError, ToolRegistry, ToolSpec, UnknownToolError

REPO_ROOT = Path(__file__).resolve().parents[4]


class LiveKitConnection(BaseModel):
    url: str
    room: str
    token: str


class ToolCall(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolInvocation(BaseModel):
    status: Literal["executed", "confirmation_required", "denied", "failed"]
    tool: str
    token: str | None = None
    result: Any = None
    error: str | None = None
    runtime: RuntimeStatus | None = None


class ToolDescription(BaseModel):
    name: str
    description: str
    sensitive: bool
    arguments: list[str]
    optional: list[str]


class ToolCatalog(BaseModel):
    tools: list[ToolDescription]


class RoomEventPage(BaseModel):
    events: list[dict[str, Any]]


def livekit_is_ready(host: str = "127.0.0.1", port: int = 7880) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.05):
            return True
    except OSError:
        return False


def read_version(root: Path = REPO_ROOT) -> str:
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def create_app(
    version: str | None = None,
    runtime: RuntimeStore | None = None,
    tools: ToolRegistry | None = None,
) -> FastAPI:
    product_version = version or read_version()
    runtime_store = runtime or RuntimeStore()
    sidecar: RoomSidecar | None = None
    if tools is not None:
        tool_registry = tools
    else:
        tool_registry = ToolRegistry()
        sidecar = RoomSidecar()
        register_room_tools(tool_registry, sidecar)
    app = FastAPI(title="Marvi Gateway", version=product_version, docs_url=None, redoc_url=None)

    def room_status() -> ComponentStatus:
        if sidecar is None:
            return ComponentStatus(state="offline", detail="sidecar not connected")
        state, detail = sidecar.status()
        return ComponentStatus(state=state, detail=detail)  # type: ignore[arg-type]

    def current_status() -> RuntimeStatus:
        if sidecar is not None:
            runtime_store.observe_room_event(sidecar.latest_notable_event())
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
                "room": room_status(),
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

    def run_tool(spec: ToolSpec, arguments: dict[str, Any]) -> ToolInvocation:
        try:
            result = tool_registry.execute(spec, arguments)
        except Exception as exc:  # a sidecar failure must never take down voice
            runtime_store.audit("failed", spec.name, arguments, detail=str(exc))
            return ToolInvocation(
                status="failed", tool=spec.name, error=str(exc), runtime=current_status()
            )
        runtime_store.audit("executed", spec.name, arguments)
        return ToolInvocation(
            status="executed", tool=spec.name, result=result, runtime=current_status()
        )

    @app.get("/tools", response_model=ToolCatalog)
    async def list_tools() -> ToolCatalog:
        return ToolCatalog(
            tools=[
                ToolDescription(
                    name=spec.name,
                    description=spec.description,
                    sensitive=spec.sensitive,
                    arguments=sorted(spec.arguments),
                    optional=sorted(spec.optional),
                )
                for spec in tool_registry
            ]
        )

    @app.post("/tools/{name}", response_model=ToolInvocation)
    async def call_tool(name: str, call: ToolCall) -> ToolInvocation:
        try:
            spec = tool_registry.get(name)
        except UnknownToolError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            arguments = tool_registry.validate(spec, call.arguments)
        except InvalidArgumentsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        runtime_store.audit("requested", spec.name, arguments)

        if spec.sensitive and not runtime_store.assistant.yolo:
            request = runtime_store.issue_confirmation(
                tool=spec.name,
                arguments=arguments,
                action=spec.description,
                detail=spec.summary(arguments),
            )
            runtime_store.audit("confirmation_required", spec.name, arguments)
            return ToolInvocation(
                status="confirmation_required",
                tool=spec.name,
                token=request.token,
                runtime=current_status(),
            )

        return run_tool(spec, arguments)

    @app.post("/confirmations/{token}", response_model=ToolInvocation)
    async def resolve_confirmation(
        token: str, decision: ConfirmationDecision
    ) -> ToolInvocation:
        try:
            pending = runtime_store.take_confirmation(token, decision.arguments)
        except ArgumentsMutatedError as exc:
            raise HTTPException(
                status_code=409, detail="confirmation arguments do not match"
            ) from exc
        except TokenRejectedError as exc:
            raise HTTPException(status_code=404, detail="confirmation not found") from exc

        spec = tool_registry.get(pending.tool)
        if decision.decision == "deny":
            runtime_store.audit("denied", pending.tool, pending.arguments)
            runtime_store.settle_confirmation(
                token, caption="Action denied", action=spec.description
            )
            return ToolInvocation(
                status="denied", tool=pending.tool, runtime=current_status()
            )

        runtime_store.audit("approved", pending.tool, pending.arguments)
        runtime_store.settle_confirmation(
            token, caption="Action approved", action=spec.description
        )
        return run_tool(spec, pending.arguments)

    @app.get("/room/events", response_model=RoomEventPage)
    async def room_events(limit: int = 50, notable_only: bool = True) -> RoomEventPage:
        if sidecar is None:
            return RoomEventPage(events=[])
        return RoomEventPage(
            events=sidecar.events(limit=max(1, min(limit, 200)), notable_only=notable_only)
        )

    @app.get("/audit", response_model=AuditPage)
    async def audit_tail(limit: int = 100) -> AuditPage:
        return AuditPage(events=runtime_store.recent_audit(limit=max(1, min(limit, 500))))

    return app


app = create_app()
