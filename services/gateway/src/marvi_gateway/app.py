from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from livekit import api
from pydantic import BaseModel, Field

from .accounts import ComposioAccounts, register_account_tools
from .browser import BrowserSession, browser_enabled, register_browser_tools
from .ingest import AccountIngest
from .initiative import Initiative
from .journal import EventJournal
from .mcp_bridge import McpBridge, register_mcp_tools
from .memory import MemoryStore, register_memory_tools
from .mind import Mind
from .policy import InitiativeSettings
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
from .web import WebTools, register_web_tools
from .workspace import Workspace, register_workspace_tools

REPO_ROOT = Path(__file__).resolve().parents[4]


class LiveKitConnection(BaseModel):
    url: str
    room: str
    token: str


class ToolCall(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class ToolInvocation(BaseModel):
    status: Literal["executed", "confirmation_required", "denied", "failed"]
    tool: str
    token: str | None = None
    result: Any = None
    error: str | None = None
    deduplicated: bool = False
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


class MemoryPage(BaseModel):
    total: int
    entries: list[dict[str, Any]]
    summary: dict[str, Any]


class IngestResult(BaseModel):
    ingested: list[str]
    skipped: int
    errors: list[str]


class ReflectResult(BaseModel):
    considered: int
    promoted: list[str]


class ConsolidateResult(BaseModel):
    forgotten: int
    orphan_entities: int


class MemoryExport(BaseModel):
    entries: list[dict[str, Any]]


class InitiativeUpdate(BaseModel):
    paused: bool


class InitiativeStatus(BaseModel):
    paused: bool
    running: bool
    pending_events: int
    last_runs: dict[str, str]
    last_errors: dict[str, str]
    settings: dict[str, Any]


class DecisionPage(BaseModel):
    decisions: list[dict[str, Any]]
    events: list[dict[str, Any]]


class MindResult(BaseModel):
    considered: int
    decisions: list[dict[str, Any]]
    surfaced: list[dict[str, Any]]


class AccountRow(BaseModel):
    toolkit: str
    status: str
    connected: bool
    needs_reconnect: bool


class AccountPage(BaseModel):
    available: bool
    detail: str
    accounts: list[AccountRow]


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
    accounts: ComposioAccounts | None = None
    memory: MemoryStore | None = None
    ingest: AccountIngest | None = None
    journal: EventJournal | None = None
    initiative: Initiative | None = None
    if tools is not None:
        tool_registry = tools
    else:
        tool_registry = ToolRegistry()
        sidecar = RoomSidecar()
        register_room_tools(tool_registry, sidecar)
        accounts = ComposioAccounts()
        if accounts.available():
            register_account_tools(tool_registry, accounts)
        memory = MemoryStore()
        register_memory_tools(tool_registry, memory)
        if accounts.available():
            ingest = AccountIngest(accounts, memory)
        register_web_tools(tool_registry, WebTools())
        workspace = Workspace()
        if workspace.available():
            register_workspace_tools(tool_registry, workspace)
        journal = EventJournal()
        initiative = Initiative(
            Mind(journal, memory=memory, settings=InitiativeSettings.from_env()),
            journal,
            ingest=ingest,
            memory=memory,
            room_state=(lambda: {"present": bool(
                ((sidecar.snapshot() or {}).get("presence") or {}).get("detected", True)
            )}) if sidecar is not None else None,
        )
        if browser_enabled():
            # A headless browser is a real resource cost, so it stays off until
            # MARVI_BROWSER asks for it.
            register_browser_tools(tool_registry, BrowserSession(), workspace)
        mcp = McpBridge()
        if mcp.available():
            # Routed here rather than attached to the Agent so MCP tools
            # inherit confirmation, audit, and idempotency (ADR-016).
            register_mcp_tools(tool_registry, mcp)
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # The background mind starts with the Gateway and stops with it, so a
        # restart never leaves an orphaned scheduler ticking.
        if initiative is not None:
            initiative.start()
        try:
            yield
        finally:
            if initiative is not None:
                initiative.stop()

    app = FastAPI(
        title="Marvi Gateway",
        version=product_version,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    def accounts_status() -> ComponentStatus:
        if accounts is None or not accounts.available():
            return ComponentStatus(state="pending", detail="no Composio API key configured")
        try:
            rows = accounts.cached_connections()
        except Exception as exc:
            return ComponentStatus(state="error", detail=str(exc)[:120])
        live = sum(1 for row in rows if row["connected"])
        stale = sum(1 for row in rows if row["needs_reconnect"])
        if not rows:
            return ComponentStatus(state="pending", detail="no accounts connected")
        detail = f"{live} connected" + (f", {stale} need reconnect" if stale else "")
        return ComponentStatus(state="ready" if live else "error", detail=detail)

    def room_status() -> ComponentStatus:
        if sidecar is None:
            return ComponentStatus(state="offline", detail="sidecar not connected")
        state, detail = sidecar.status()
        return ComponentStatus(state=state, detail=detail)  # type: ignore[arg-type]

    def current_status() -> RuntimeStatus:
        if sidecar is not None:
            latest = sidecar.latest_notable_event()
            runtime_store.observe_room_event(latest)
            if latest and journal is not None:
                # A room transition is a world event the mind may reason about.
                journal.append(
                    "room",
                    str(latest.get("type", "event")),
                    str(latest.get("summary", "room event")),
                    {"id": latest.get("id")},
                    trusted=True,
                )
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
                "accounts": accounts_status(),
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

    def run_tool(
        spec: ToolSpec, arguments: dict[str, Any], write_key: str | None = None
    ) -> ToolInvocation:
        try:
            result = tool_registry.execute(spec, arguments)
        except Exception as exc:  # a sidecar failure must never take down voice
            # A failed write is not a completed write: leave it retryable.
            runtime_store.audit("failed", spec.name, arguments, detail=str(exc))
            return ToolInvocation(
                status="failed", tool=spec.name, error=str(exc), runtime=current_status()
            )
        if write_key is not None:
            runtime_store.record_external_write(write_key, result)
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

        write_key: str | None = None
        if spec.external:
            write_key = runtime_store.external_write_key(
                spec.name, arguments, call.idempotency_key
            )
            already_done, previous = runtime_store.completed_external_write(write_key)
            if already_done:
                # Checked before confirmation on purpose: the action already
                # happened, so asking again would be a second decision about a
                # thing that is already done.
                runtime_store.audit("deduplicated", spec.name, arguments)
                return ToolInvocation(
                    status="executed",
                    tool=spec.name,
                    result=previous,
                    deduplicated=True,
                    runtime=current_status(),
                )

        if spec.sensitive and not runtime_store.assistant.yolo:
            request = runtime_store.issue_confirmation(
                tool=spec.name,
                arguments=arguments,
                action=spec.description,
                detail=spec.summary(arguments),
                write_key=write_key,
            )
            runtime_store.audit("confirmation_required", spec.name, arguments)
            return ToolInvocation(
                status="confirmation_required",
                tool=spec.name,
                token=request.token,
                runtime=current_status(),
            )

        return run_tool(spec, arguments, write_key)

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
        return run_tool(spec, pending.arguments, pending.write_key)

    @app.get("/memory", response_model=MemoryPage)
    async def memory_page(limit: int = 50) -> MemoryPage:
        if memory is None:
            return MemoryPage(total=0, entries=[], summary={})
        return MemoryPage(
            total=memory.count(),
            entries=memory.recent(limit=max(1, min(limit, 200))),
            summary=memory.world_summary(),
        )

    @app.post("/accounts/ingest", response_model=IngestResult)
    async def run_ingest() -> IngestResult:
        """One bounded ingestion tick. Safe to call repeatedly; duplicates are
        skipped by provider id."""
        if ingest is None:
            return IngestResult(ingested=[], skipped=0, errors=["accounts not configured"])
        result = ingest.poll()
        if result["ingested"]:
            runtime_store.audit(
                "ingested", "accounts", {"count": len(result["ingested"])}
            )
        return IngestResult(**{k: v for k, v in result.items() if k != "at"})

    @app.post("/memory/reflect", response_model=ReflectResult)
    async def run_reflect() -> ReflectResult:
        if memory is None:
            return ReflectResult(considered=0, promoted=[])
        return ReflectResult(**memory.reflect())

    @app.post("/memory/consolidate", response_model=ConsolidateResult)
    async def run_consolidate() -> ConsolidateResult:
        if memory is None:
            return ConsolidateResult(forgotten=0, orphan_entities=0)
        result = memory.consolidate()
        runtime_store.audit("consolidated", "memory", result)
        return ConsolidateResult(**result)

    @app.post("/memory/export", response_model=MemoryExport)
    async def memory_export() -> MemoryExport:
        return MemoryExport(entries=memory.export() if memory else [])

    @app.delete("/memory", response_model=MemoryPage)
    async def memory_clear() -> MemoryPage:
        if memory is None:
            return MemoryPage(total=0, entries=[], summary={})
        runtime_store.audit("memory_cleared", "memory", {"removed": memory.forget_all()})
        return MemoryPage(total=0, entries=[], summary=memory.world_summary())

    @app.get("/initiative", response_model=InitiativeStatus)
    async def initiative_status() -> InitiativeStatus:
        if initiative is None:
            return InitiativeStatus(paused=True, running=False, pending_events=0,
                                    last_runs={}, last_errors={}, settings={})
        return InitiativeStatus(**initiative.status())

    @app.put("/initiative", response_model=InitiativeStatus)
    async def set_initiative(update: InitiativeUpdate) -> InitiativeStatus:
        if initiative is None:
            return InitiativeStatus(paused=True, running=False, pending_events=0,
                                    last_runs={}, last_errors={}, settings={})
        initiative.set_paused(update.paused)
        runtime_store.audit(
            "initiative", "mind", {"paused": update.paused}
        )
        return InitiativeStatus(**initiative.status())

    @app.get("/mind/decisions", response_model=DecisionPage)
    async def mind_decisions(limit: int = 50) -> DecisionPage:
        if journal is None:
            return DecisionPage(decisions=[], events=[])
        return DecisionPage(
            decisions=journal.decisions(limit=max(1, min(limit, 200))),
            events=journal.recent(limit=max(1, min(limit, 200))),
        )

    @app.post("/mind/tick", response_model=MindResult)
    async def mind_tick() -> MindResult:
        """Run one mind turn now. Safe to call repeatedly; events are decided once."""
        if initiative is None:
            return MindResult(considered=0, decisions=[], surfaced=[])
        return MindResult(**initiative.run_mind())

    @app.get("/accounts", response_model=AccountPage)
    async def account_page() -> AccountPage:
        if accounts is None or not accounts.available():
            return AccountPage(
                available=False, detail="No Composio API key configured", accounts=[]
            )
        try:
            rows = accounts.cached_connections()
        except Exception as exc:
            return AccountPage(available=True, detail=str(exc)[:160], accounts=[])
        return AccountPage(
            available=True,
            detail=f"{sum(1 for r in rows if r['connected'])} of {len(rows)} connected",
            accounts=[AccountRow(**row) for row in rows],
        )

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
