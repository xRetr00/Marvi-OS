from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from livekit import api
from pydantic import BaseModel, Field

from . import breadcrumb, latency, paths
from . import doctor as doctor_module
from . import plugins as plugins_module
from . import room as room_module
from . import schedule as schedule_module
from . import setup as setup_module
from .accounts import ComposioAccounts, register_account_tools
from .activity import ActivityWatch, register_activity_tools
from .announce import Announcer, announce_enabled
from .browser import BrowserSession, browser_enabled, register_browser_tools
from .chat import Chat, ChatStore, ChatTurn, schemas_from_registry
from .curiosity import Curiosity, seed_identity
from .deliberate import deliberator_from_env
from .identity import IdentityFiles, plan_warning
from .ingest import AccountIngest
from .initiative import Initiative
from .journal import EventJournal
from .logs import available as available_logs
from .logs import configure as configure_logging
from .logs import get_logger, install_asyncio_handler, logs_dir, redactor, tail
from .mcp_bridge import McpBridge, register_mcp_tools
from .memory import MemoryStore, register_memory_tools
from .mind import Mind
from .policy import InitiativeSettings
from .providers import ProviderClient, all_profiles
from .providers import config as provider_config
from .providers.oauth import OAuthError, broker
from .room import RoomSidecar, RoomUnavailableError, register_room_tools, sleep_guard
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
from .vision import FaceLibrary, VisionService, register_vision_tools
from .web import WebTools, register_web_tools
from .workspace import Workspace, register_workspace_tools

# Long enough for a loopback connect, short enough that a page listing a dozen
# dead local endpoints still renders immediately.
LOCAL_PROBE_TIMEOUT = 0.4

#: Live download progress by component name, while an install is in flight.
#: Module level because the install request and the polling request are
#: different requests; it is a readout, not state anything depends on.
_install_progress: dict[str, dict[str, Any]] = {}

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
    # All optional: the page sends only what changed. Every one of these
    # changes how often Marvi speaks, so none of them belongs in a constant.
    paused: bool | None = None
    quiet_start: int | None = Field(default=None, ge=0, le=23)
    quiet_end: int | None = Field(default=None, ge=0, le=23)
    cooldown_seconds: int | None = Field(default=None, ge=0, le=86_400)
    daily_token_budget: int | None = Field(default=None, ge=0)
    speak_when_away: bool | None = None


class InitiativeStatus(BaseModel):
    paused: bool
    running: bool
    pending_events: int
    last_runs: dict[str, str]
    last_errors: dict[str, str]
    settings: dict[str, Any]


class ProviderRow(BaseModel):
    name: str
    label: str
    access_path: str
    api_mode: str
    auth_type: str
    configured: bool
    base_url: str
    models: dict[str, str]
    # The variables this provider reads, so the GUI edits exactly those rather
    # than deriving names from the provider's own and getting them wrong.
    env: dict[str, str]
    limits: dict[str, Any]
    usage: dict[str, int]
    cooldown: dict[str, Any] | None
    # Sign-in state for OAuth providers; None for everything else.
    oauth: dict[str, Any] | None
    warning: str | None
    # Local providers only: is something listening on the endpoint right now?
    # None means "not probed" — a remote API is not pinged just to draw a page.
    reachable: bool | None = None


class ProviderPage(BaseModel):
    providers: list[ProviderRow]
    selected: str | None
    settings: dict[str, str]
    totals: dict[str, int]


class OAuthStart(BaseModel):
    """Where to send the user. Marvi never renders the provider's login itself."""

    url: str
    redirect_uri: str


class ProviderSettingsUpdate(BaseModel):
    # Plain environment variable names, so the GUI edits exactly what the
    # registry reads. An empty value clears the setting and disconnects.
    values: dict[str, str]


class VoiceProvider(BaseModel):
    """What the Agent worker needs to build its LLM. Loopback only."""

    provider: str
    base_url: str
    model: str
    api_key: str


class IdentityStatus(BaseModel):
    soul: str
    user: str
    tokens: int
    budget: int
    truncated: bool
    directory: str


class IdentityUpdate(BaseModel):
    soul: str | None = None
    user: str | None = None


class ChatMessage(BaseModel):
    message: str


class ChatReply(BaseModel):
    reply: str
    tools_used: list[str]
    # Set when a sensitive action was requested: the same token the Island and
    # the voice path resolve, so no surface has a private way to say yes.
    pending_confirmation: dict[str, Any] | None
    tokens: int
    provider: str
    error: str


class ChatHistory(BaseModel):
    messages: list[dict[str, Any]]
    available: bool


class DoctorReport(BaseModel):
    findings: list[dict[str, Any]]
    summary: dict[str, int]
    healthy: bool


class HealRequest(BaseModel):
    # Automatic remedies always run. Anything that spends money, takes real
    # time, or touches another process needs this set.
    include_confirmed: bool = False


class HealResult(BaseModel):
    applied: list[dict[str, Any]]
    report: DoctorReport


class ComponentRow(BaseModel):
    name: str
    kind: str
    title: str
    why: str
    needed_for: list[str]
    bytes_total: int
    installed: bool
    detail: str
    #: Bytes fetched so far while an install is running, else None. The install
    #: endpoint blocks for as long as the download takes, so this is what the
    #: page polls to show anything at all during it.
    progress: dict[str, Any] | None = None


class SetupPage(BaseModel):
    components: list[ComponentRow]
    plan: dict[str, Any]
    install_root: str
    disk_ok: bool
    disk_detail: str


class ScheduleRow(BaseModel):
    id: int
    name: str
    action: str
    kind: str
    expression: str
    message: str
    enabled: bool
    created_at: str
    insist: bool
    last_run: str | None = None
    last_error: str | None = None


class SchedulePage(BaseModel):
    schedules: list[ScheduleRow]
    #: What a schedule may trigger, so the page can offer exactly those.
    actions: dict[str, str]
    running: bool


class NewSchedule(BaseModel):
    name: str
    when: str
    message: str = ""
    action: str = "remind"
    insist: bool = False


class PluginRow(BaseModel):
    name: str
    title: str
    why: str
    repo: str
    ref: str
    installed: bool
    version: str
    commit: str
    tools: list[str]
    detail: str
    supported: bool


class PluginPage(BaseModel):
    plugins: list[PluginRow]
    #: Where checkouts live and where plugin data lives, shown because a plugin
    #: is a thing on disk the user may want to look at.
    install_root: str
    data_root: str


class GpuAnswer(BaseModel):
    use_gpu: bool


class McpPrepare(BaseModel):
    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class McpApprove(BaseModel):
    token: str


class SkillInstall(BaseModel):
    repo: str
    path: str


class SkillConfirm(BaseModel):
    staged: str


class LogPage(BaseModel):
    subsystem: str
    lines: list[str]
    available: list[str]
    directory: str


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


def load_installed_plugins() -> list[plugins_module.LoadedPlugin]:
    """Import every installed plugin. A broken one is skipped, not fatal.

    A plugin failing to load is a Marvi with less in it, not a Marvi that
    cannot start — and the Doctor page is a better place to explain that than a
    Gateway which refuses to boot.
    """
    found = []
    for row in plugins_module.status(REPO_ROOT):
        if not row["installed"] or not row["supported"]:
            continue
        try:
            found.append(plugins_module.load(row["name"]))
        except plugins_module.PluginError as exc:
            get_logger("plugins").error(
                "plugin failed to load",
                extra={"marvi_plugin": row["name"], "marvi_error": str(exc)[:300]},
            )
    return found


def create_app(
    version: str | None = None,
    runtime: RuntimeStore | None = None,
    tools: ToolRegistry | None = None,
) -> FastAPI:
    product_version = version or read_version()
    # Before anything opens a database or a log: move whatever is still in the
    # old space-named folder. Someone's memory and identity live in there, and
    # silently starting fresh would look exactly like data loss.
    moved = paths.migrate_legacy()
    # Saved GUI settings become environment variables before anything reads
    # them, so the registry still has exactly one source of truth.
    provider_config.load_into_environ()
    # Logging first, and after the settings load so the redactor already knows
    # every credential before a single line can be written.
    configure_logging()
    redactor().refresh()
    # Say once that last time ended badly, then forget it. A crash nobody is
    # told about is a pattern nobody spots.
    if moved:
        configure_logging()
        get_logger("setup").info(
            "moved %d item(s) out of the old folder", len(moved),
            extra={"marvi_moved": ", ".join(moved)},
        )
    breadcrumb.install("gateway")
    last_crashes = breadcrumb.report_and_clear()
    provider_client = ProviderClient()
    identity = IdentityFiles()
    # Ship the default soul on first run. Seeded once and never overwritten:
    # an update that replaced the user's edited SOUL.md would be the worst
    # possible behaviour for a file describing who Marvi is.
    seed_identity(identity, REPO_ROOT)
    curiosity = Curiosity(identity=identity)
    chat: Chat | None = None
    runtime_store = runtime or RuntimeStore()
    sidecar: RoomSidecar | None = None
    accounts: ComposioAccounts | None = None
    memory: MemoryStore | None = None
    ingest: AccountIngest | None = None
    journal: EventJournal | None = None
    initiative: Initiative | None = None
    faces: FaceLibrary | None = None
    loaded_plugins: list[plugins_module.LoadedPlugin] = []
    #: Highest room event id already journaled. None until the first poll sets a
    #: baseline, so a restart does not replay the log into the mind.
    room_cursor: int | None = None
    scheduler: schedule_module.Scheduler | None = None
    if tools is not None:
        tool_registry = tools
    else:
        tool_registry = ToolRegistry()
        sidecar = RoomSidecar()
        register_room_tools(tool_registry, sidecar)
        # Installed plugins, after the built-in tools: a plugin cannot replace a
        # tool Marvi already registered, only add to the set. `load` imports and
        # collects; nothing is started until the lifespan opens.
        scheduler = schedule_module.Scheduler(schedule_module.ScheduleStore())
        schedule_module.register_schedule_tools(tool_registry, scheduler)
        loaded_plugins.extend(load_installed_plugins())
        for plugin in loaded_plugins:
            # The guard is Marvi's, not the plugin's. The room plugin's own
            # handlers know nothing about the sleep rule, so bridging them
            # without it would open a second path to the light that skips the
            # guard the built-in tools apply.
            plugins_module.bridge_tools(
                tool_registry,
                plugin,
                guard=sleep_guard(sidecar) if plugin.name == room_module.PLUGIN_NAME else None,
                read_only=(
                    room_module.READ_ONLY_PLUGIN_TOOLS
                    if plugin.name == room_module.PLUGIN_NAME
                    else frozenset()
                ),
            )
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
        activity = ActivityWatch()
        if activity.available():
            register_activity_tools(tool_registry, activity)
        vision = VisionService()
        if vision.available():
            faces = vision.library
            register_vision_tools(tool_registry, vision)
        journal = EventJournal()
        initiative = Initiative(
            Mind(
                journal,
                memory=memory,
                settings=InitiativeSettings.from_env(),
                deliberate=deliberator_from_env(client=provider_client),
                announcer=Announcer() if announce_enabled() else None,
            ),
            journal,
            ingest=ingest,
            memory=memory,
            faces=faces,
            room_state=(lambda: {"present": bool(
                ((sidecar.snapshot() or {}).get("presence") or {}).get("detected", True)
            )}) if sidecar is not None else None,
        )
        if browser_enabled():
            # A headless browser is a real resource cost, so it stays off until
            # MARVI_BROWSER asks for it.
            register_browser_tools(tool_registry, BrowserSession(), workspace)
        chat = Chat(
            store=ChatStore(),
            client=provider_client,
            identity=identity,
            memory=memory,
            curiosity=curiosity,
            # Their context lines reach the prompt. The room's carries what its
            # engine already knows, including its own vision block, which Marvi
            # was collecting and never reading.
            plugins=loaded_plugins,
        )
        mcp = McpBridge()
        if mcp.available():
            # Routed here rather than attached to the Agent so MCP tools
            # inherit confirmation, audit, and idempotency (ADR-016).
            register_mcp_tools(tool_registry, mcp)
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # The background mind starts with the Gateway and stops with it, so a
        # restart never leaves an orphaned scheduler ticking.
        # asyncio reports unretrieved task exceptions to a stderr nobody reads.
        install_asyncio_handler(asyncio.get_running_loop())
        if initiative is not None:
            initiative.start()
        if scheduler is not None:
            # The journal and initiative are wired in here rather than at
            # construction, because the tools are registered before either
            # exists and a reminder needs the journal to fire into.
            scheduler.journal = journal
            scheduler.initiative = initiative
            scheduler.start()
        # A plugin's backend is a child process it starts itself, on a worker
        # thread because starting one is blocking work and the event loop is
        # serving the health endpoint the shell polls every two seconds.
        for plugin in loaded_plugins:
            await anyio.to_thread.run_sync(
                lambda p=plugin: plugins_module.fire(p, "on_gateway_start")
            )
        try:
            yield
        finally:
            if initiative is not None:
                initiative.stop()
            if scheduler is not None:
                scheduler.stop()
            # Stopped in reverse, and never allowed to raise: a plugin that
            # cannot shut down cleanly must not leave the rest of the shutdown
            # undone, or its child process outlives the Gateway and holds the
            # port the next one needs.
            for plugin in reversed(loaded_plugins):
                plugins_module.fire(plugin, "on_gateway_stop")

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

    def overall_state(components: dict[str, ComponentStatus]) -> str:
        """The single light the shell waits on.

        This used to be hardcoded to "starting", so the connecting overlay
        waited for a `ready` that could never arrive and the app hung on the
        connecting page forever — in packaged builds and in dev alike.
        """
        if components["gateway"].state != "ready":
            return "starting"
        # Optional subsystems are allowed to be absent; the Gateway being up is
        # what "ready" means. Anything erroring downgrades to degraded so the
        # status bar can say so without blocking the app.
        if any(c.state == "error" for c in components.values()):
            return "degraded"
        return "ready"

    def voice_status(livekit_ready: bool) -> ComponentStatus:
        """Whether a voice session could actually happen, and if not, why.

        This was pinned at `starting` with the detail "native streaming worker
        available" — permanently, whatever the truth was. A status that never
        changes is not a status, and it was the source of the meaningless
        `VOICE STARTING` in the status bar.

        The Gateway cannot see the agent worker directly, so it reports the two
        things it *can* check, and says which one is missing rather than
        implying it knows more than it does.
        """
        if not livekit_ready:
            return ComponentStatus(
                state="pending", detail="no LiveKit server to carry the session"
            )
        missing = [
            component.title
            for component in setup_module.for_capability(REPO_ROOT, "voice")
            # Shallow: this runs on every health poll, and hashing the voice
            # models took 2.4 seconds a time — which is what made the Gateway
            # unavailable while one of them was downloading.
            if not setup_module.state_of(component, REPO_ROOT, deep=False)["installed"]
        ]
        if missing:
            return ComponentStatus(
                state="pending",
                detail=f"not installed: {', '.join(missing[:3])} — run `marvi setup voice`",
            )
        return ComponentStatus(state="ready", detail="LiveKit up, voice models installed")

    def drain_room_events() -> dict[str, Any] | None:
        """Journal every room event since the last poll. Returns the newest.

        Two bugs lived here. It read *one* event per poll, so a second notable
        thing in the same interval was lost; and it re-appended whatever the
        newest event was on every poll, so the journal's six-hour dedupe window
        was the only thing stopping a light change from yesterday re-entering the
        mind's queue forever — which it did, every six hours.

        The cursor fixes both: only genuinely new events are journaled, and all
        of them are.
        """
        nonlocal room_cursor
        if sidecar is None:
            return None
        try:
            fresh = sidecar.events_since(room_cursor)
        except RoomUnavailableError:
            # The room being down is not a Gateway problem; the component status
            # says so, and the poll must not fail because of it.
            return None
        if room_cursor is None:
            # First poll establishes a baseline. Whatever is already in the log
            # happened before Marvi was running and is not news.
            latest = sidecar.latest_notable_event()
            if latest is not None:
                room_cursor = int(latest.get("id", 0))
            return latest
        for event in fresh:
            room_cursor = max(room_cursor, int(event.get("id", 0)))
            if journal is not None:
                # A room transition is a world event the mind may reason about.
                journal.append(
                    "room",
                    str(event.get("type", "event")),
                    str(event.get("summary", "room event")),
                    {"id": event.get("id")},
                    trusted=True,
                )
        return fresh[-1] if fresh else None

    def current_status() -> RuntimeStatus:
        if sidecar is not None:
            runtime_store.observe_room_event(drain_room_events())
        livekit_ready = livekit_is_ready()
        components = {
                "gateway": ComponentStatus(state="ready", detail="local facade online"),
                "livekit": ComponentStatus(
                    state="ready" if livekit_ready else "pending",
                    detail="local server online" if livekit_ready else "local server not running",
                ),
                "voice": voice_status(livekit_ready),
                "vision": ComponentStatus(
                    state="ready" if faces is not None else "pending",
                    detail=(
                        f"buffalo_l on CPU, owner: {faces.owner_name() or 'not enrolled'}"
                        if faces is not None else "set MARVI_VISION to enable"
                    ),
                ),
                "accounts": accounts_status(),
                "room": room_status(),
        }
        return RuntimeStatus(
            product="Marvi OS",
            version=product_version,
            state=overall_state(components),
            components=components,
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

    def dispatch_for_chat(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run a tool for chat through exactly the path voice uses.

        Chat gets no private door: an unknown tool, bad arguments, and a
        sensitive action all behave here the way they do over HTTP.
        """
        try:
            spec = tool_registry.get(name)
            checked = tool_registry.validate(spec, arguments)
        except (UnknownToolError, InvalidArgumentsError) as exc:
            return {"status": "failed", "error": str(exc)}

        runtime_store.audit("requested", spec.name, checked, detail="via chat")
        write_key = (
            runtime_store.external_write_key(spec.name, checked, None)
            if spec.external
            else None
        )
        if spec.sensitive and not runtime_store.assistant.yolo:
            request = runtime_store.issue_confirmation(
                tool=spec.name,
                arguments=checked,
                action=spec.description,
                detail=spec.summary(checked),
                write_key=write_key,
            )
            runtime_store.audit("confirmation_required", spec.name, checked)
            return {"status": "confirmation_required", "token": request.token}
        return run_tool(spec, checked, write_key).model_dump()

    if chat is not None:
        chat.dispatch = dispatch_for_chat
        chat.tool_schemas = lambda: schemas_from_registry(tool_registry)

    @app.get("/chat", response_model=ChatHistory)
    async def chat_history() -> ChatHistory:
        if chat is None:
            return ChatHistory(messages=[], available=False)
        return ChatHistory(messages=chat.store.history(limit=200), available=chat.available())

    @app.post("/chat", response_model=ChatReply)
    async def chat_send(body: ChatMessage) -> ChatReply:
        if chat is None:
            raise HTTPException(status_code=503, detail="chat is not available")
        # Blocking call on the event loop would stall the health endpoint the
        # shell polls every two seconds, so it runs on a worker thread.
        import anyio

        turn: ChatTurn = await anyio.to_thread.run_sync(chat.send, body.message)
        return ChatReply(
            reply=turn.reply,
            tools_used=turn.tools_used,
            pending_confirmation=turn.pending_confirmation,
            tokens=turn.tokens,
            provider=turn.provider,
            error=turn.error,
        )

    @app.delete("/chat", response_model=ChatHistory)
    async def chat_clear() -> ChatHistory:
        if chat is None:
            return ChatHistory(messages=[], available=False)
        removed = chat.store.clear()
        runtime_store.audit("chat", "cleared", {"messages": removed})
        return ChatHistory(messages=[], available=chat.available())

    def doctor_report() -> DoctorReport:
        findings = doctor_module.run_checks()
        counts = doctor_module.summary(findings)
        return DoctorReport(
            findings=[f.as_dict() for f in findings],
            summary=counts,
            healthy=counts["fail"] == 0,
        )

    @app.get("/doctor", response_model=DoctorReport)
    async def run_doctor() -> DoctorReport:
        return doctor_report()

    @app.get("/doctor/crashes")
    async def crashes() -> dict[str, Any]:
        """What was left behind by an unclean exit, read at startup."""
        return {"crashes": last_crashes}

    @app.post("/doctor/heal", response_model=HealResult)
    async def heal(request: HealRequest) -> HealResult:
        findings = doctor_module.run_checks()
        applied = doctor_module.heal(findings, include_confirmed=request.include_confirmed)
        for entry in applied:
            runtime_store.audit("doctor", "healed", entry)
        # Re-run afterwards: the report has to reflect the repair, not the
        # state that prompted it.
        return HealResult(applied=applied, report=doctor_report())

    @app.get("/doctor/diagnostics")
    async def diagnostics() -> dict[str, str]:
        """One redacted block to paste into a bug report."""
        return {"text": doctor_module.diagnostics()}

    def setup_page() -> SetupPage:
        components = setup_module.load(REPO_ROOT)
        enough, detail = setup_module.disk_space_for(components)
        rows = []
        for component in components:
            state = setup_module.state_of(component, REPO_ROOT)
            rows.append(
                ComponentRow(
                    name=component.name,
                    kind=component.kind,
                    title=component.title,
                    why=component.why,
                    needed_for=list(component.needed_for),
                    bytes_total=component.bytes_total,
                    installed=bool(state["installed"]),
                    detail=str(state["detail"]),
                    progress=_install_progress.get(component.name),
                )
            )
        return SetupPage(
            components=rows,
            plan=setup_module.plan(components),
            install_root=str(setup_module.install_root()),
            disk_ok=enough,
            disk_detail=detail,
        )

    def plugin_page() -> PluginPage:
        return PluginPage(
            plugins=[PluginRow(**row) for row in plugins_module.status(REPO_ROOT)],
            install_root=str(plugins_module.root()),
            data_root=str(plugins_module.data_root()),
        )

    def schedule_page() -> SchedulePage:
        if scheduler is None:
            return SchedulePage(schedules=[], actions={}, running=False)
        state = scheduler.status()
        return SchedulePage(
            schedules=[ScheduleRow(**row) for row in state["schedules"]],
            actions=state["actions"],
            running=bool(state["running"]),
        )

    class LlmTurn(BaseModel):
        messages: list[dict[str, Any]]
        #: Which job this turn is, so the right model and later the right
        #: auxiliary slot is chosen. Not a provider name: callers say what they
        #: are doing and the Gateway decides who does it.
        job: str = "main"
        surface: str = "unknown"
        max_tokens: int | None = None
        effort: str | None = None
        temperature: float | None = None
        tools: list[dict[str, Any]] | None = None

    @app.post("/llm")
    async def llm_turn(turn: LlmTurn) -> StreamingResponse:
        """One LLM turn, streamed, for any caller.

        The seam. Chat, voice, mind and vision each reached a provider their own
        way, so fallback, cooldowns and usage applied to two of the four. They
        come here instead, and the differences between them become the `job`
        and `surface` they declare rather than four transports.

        Server-sent events, because the caller is either an Electron renderer or
        a LiveKit worker and both speak it, and because a buffered response
        would move first-token latency to the whole-response time — which on
        voice is the difference this endpoint exists to avoid.
        """

        def events() -> Iterator[str]:
            sample = latency.Sample(surface=turn.surface, path="gateway", provider="", model="")
            started = time.perf_counter()
            try:
                for piece in provider_client.stream(
                    turn.messages,
                    job=turn.job,
                    max_tokens=turn.max_tokens,
                    effort=turn.effort,
                    temperature=turn.temperature,
                    tools=turn.tools,
                ):
                    if piece.get("delta") and sample.first_token_ms is None:
                        sample.first_token_ms = (time.perf_counter() - started) * 1000
                    if piece.get("done"):
                        sample.provider = str(piece.get("provider", ""))
                        sample.model = str(piece.get("model", ""))
                    yield f"data: {json.dumps(piece)}\n\n"
            except Exception as exc:
                # Reported in the stream rather than as a status code: by the
                # time a provider fails the response has usually already begun,
                # and a caller mid-stream cannot see a header.
                sample.error = f"{type(exc).__name__}: {exc}"[:200]
                yield f"data: {json.dumps({'error': str(exc)[:200]})}\n\n"
            finally:
                sample.total_ms = (time.perf_counter() - started) * 1000
                latency.record(sample)
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            # Nothing between here and the caller may buffer: both are on
            # loopback, and a proxy that helpfully batches would undo the point.
            headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
        )

    @app.post("/latency")
    async def record_latency(sample: dict[str, Any]) -> dict[str, Any]:
        """Take a timing sample from the Agent.

        The Agent runs in its own process, so it cannot append to the recording
        the Gateway owns. It posts instead, after the turn is over.
        """
        latency.record(
            latency.Sample(
                surface=str(sample.get("surface", "unknown")),
                path=str(sample.get("path", "unknown")),
                provider=str(sample.get("provider", "")),
                model=str(sample.get("model", "")),
                first_token_ms=sample.get("first_token_ms"),
                total_ms=sample.get("total_ms"),
                error=str(sample.get("error", "")),
            )
        )
        return {"recorded": True}

    @app.get("/latency")
    async def read_latency(surface: str | None = None) -> dict[str, Any]:
        return latency.summarise(surface=surface)

    @app.get("/latency/compare")
    async def compare_latency(
        surface: str = "voice", before: str = "direct", after: str = "gateway"
    ) -> dict[str, Any]:
        """The Phase 12 gate, as a number rather than an opinion."""
        return latency.compare(surface, before, after)

    @app.get("/schedules", response_model=SchedulePage)
    async def read_schedules() -> SchedulePage:
        return schedule_page()

    @app.post("/schedules", response_model=SchedulePage)
    async def add_schedule(body: NewSchedule) -> SchedulePage:
        if scheduler is None:
            raise HTTPException(status_code=503, detail="the scheduler is not running")
        kind, expression = "cron", body.when.strip()
        if expression.isdigit():
            kind = "interval"
        elif ":" in expression and len(expression.split(":")) == 2:
            hour, _, minute = expression.partition(":")
            try:
                expression = f"{int(minute)} {int(hour)} * * *"
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail=f"{body.when!r} is not a time Marvi understands"
                ) from exc
        try:
            scheduler.store.add(
                body.name, body.action, kind, expression, body.message, insist=body.insist
            )
        except schedule_module.ScheduleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # Rebuilt so a new reminder does not wait for a restart.
        scheduler.reload()
        runtime_store.audit("schedule", "add", {"name": body.name, "when": body.when})
        return schedule_page()

    @app.post("/schedules/{schedule_id}/{action}", response_model=SchedulePage)
    async def change_schedule(schedule_id: int, action: str) -> SchedulePage:
        if scheduler is None:
            raise HTTPException(status_code=503, detail="the scheduler is not running")
        try:
            if action == "remove":
                scheduler.store.remove(schedule_id)
            elif action in ("enable", "disable"):
                scheduler.store.set_enabled(schedule_id, action == "enable")
            elif action == "run":
                scheduler.fire(schedule_id)
            else:
                raise HTTPException(status_code=400, detail=f"unknown action {action}")
        except schedule_module.ScheduleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if action != "run":
            scheduler.reload()
        runtime_store.audit("schedule", action, {"id": schedule_id})
        return schedule_page()

    @app.get("/plugins", response_model=PluginPage)
    async def read_plugins() -> PluginPage:
        return plugin_page()

    @app.post("/plugins/{name}/install", response_model=PluginPage)
    async def install_plugin(name: str) -> PluginPage:
        """Clone a plugin and install its dependencies.

        A plugin's code runs inside the Gateway and its dependencies land in the
        Gateway's environment, which is why this is a button the user presses
        and not something setup does quietly. The confirmation is the UI's.
        """
        source = plugins_module.source_for(REPO_ROOT, name)
        if source is None:
            raise HTTPException(status_code=404, detail=f"unknown plugin {name}")
        try:
            detail = await anyio.to_thread.run_sync(
                lambda: plugins_module.install(source, REPO_ROOT)
            )
        except plugins_module.PluginError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        runtime_store.audit("plugin", "install", {"plugin": name, "detail": detail})
        return plugin_page()

    @app.post("/plugins/{name}/update", response_model=PluginPage)
    async def update_plugin(name: str) -> PluginPage:
        try:
            detail = await anyio.to_thread.run_sync(
                lambda: plugins_module.update(name, REPO_ROOT)
            )
        except plugins_module.PluginError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        runtime_store.audit("plugin", "update", {"plugin": name, "detail": detail})
        return plugin_page()

    @app.post("/plugins/{name}/remove", response_model=PluginPage)
    async def remove_plugin(name: str) -> PluginPage:
        try:
            detail = plugins_module.remove(name)
        except plugins_module.PluginError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        runtime_store.audit("plugin", "remove", {"plugin": name, "detail": detail})
        return plugin_page()

    @app.get("/setup", response_model=SetupPage)
    async def read_setup() -> SetupPage:
        """What is installed, what is missing, and how big the gap is."""
        return setup_page()

    @app.post("/setup/{name}/install", response_model=SetupPage)
    async def install_component(name: str) -> SetupPage:
        component = setup_module.get(REPO_ROOT, name)
        if component is None:
            raise HTTPException(status_code=404, detail=f"unknown component {name}")
        import anyio

        def note(name: str, file: str, done: int, total: int) -> None:
            # Written from the worker thread and read by whatever polls /setup.
            # A dict assignment is atomic enough for a progress readout, and a
            # lock here would be a lock held across a multi-gigabyte download.
            _install_progress[name] = {
                "file": file,
                "bytes_done": done,
                "bytes_total": total,
            }

        # Gigabytes on a worker thread: blocking the event loop would stall the
        # health endpoint the shell polls every two seconds.
        try:
            outcome = await anyio.to_thread.run_sync(
                lambda: setup_module.install(component, REPO_ROOT, progress=note)
            )
        finally:
            # Cleared whatever happened, or a failed download leaves the page
            # showing a bar that will never move again.
            _install_progress.pop(name, None)
        runtime_store.audit("setup", "install", outcome.as_dict())
        return setup_page()

    @app.post("/setup/{name}/remove", response_model=SetupPage)
    async def remove_component(name: str) -> SetupPage:
        component = setup_module.get(REPO_ROOT, name)
        if component is None:
            raise HTTPException(status_code=404, detail=f"unknown component {name}")
        outcome = setup_module.remove(component)
        runtime_store.audit("setup", "remove", outcome.as_dict())
        return setup_page()

    @app.get("/setup/first-run")
    async def first_run() -> dict[str, Any]:
        """What is left before Marvi is useful, and what is merely nice."""
        from .setup import firstrun

        return firstrun.status(REPO_ROOT)

    @app.get("/setup/hardware")
    async def setup_hardware() -> dict[str, Any]:
        """What Marvi found, and whether it needs to ask about it."""
        from .setup import hardware

        return hardware.question()

    @app.put("/setup/hardware")
    async def choose_hardware(answer: GpuAnswer) -> dict[str, Any]:
        from .setup import hardware

        hardware.remember(answer.use_gpu)
        runtime_store.audit("setup", "gpu", {"use_gpu": answer.use_gpu})
        return hardware.question()

    @app.get("/mcp")
    async def list_mcp() -> dict[str, Any]:
        from .setup import mcp

        return {"servers": mcp.status()}

    @app.post("/mcp/prepare")
    async def prepare_mcp(request: McpPrepare) -> dict[str, Any]:
        """Describe what would run. Writes nothing, starts nothing."""
        from .setup import mcp

        return mcp.prepare(request.name, request.command, request.args, request.env)

    @app.post("/mcp/add")
    async def add_mcp(request: McpApprove) -> dict[str, Any]:
        from .setup import mcp

        result = mcp.add(request.token)
        runtime_store.audit("setup", "mcp-add", result)
        return result

    @app.post("/mcp/{name}/test")
    async def test_mcp(name: str) -> dict[str, Any]:
        import anyio

        from .setup import mcp

        server = mcp.read().get(name)
        if server is None:
            raise HTTPException(status_code=404, detail=f"no server named {name}")
        return await anyio.to_thread.run_sync(lambda: mcp.test(server))

    @app.delete("/mcp/{name}")
    async def remove_mcp(name: str) -> dict[str, Any]:
        from .setup import mcp

        result = mcp.remove(name)
        runtime_store.audit("setup", "mcp-remove", result)
        return result

    @app.get("/skills")
    async def list_skills() -> dict[str, Any]:
        from .setup import skills

        return {"skills": [s.as_dict() for s in skills.installed()]}

    @app.get("/skills/store")
    async def browse_skills() -> dict[str, Any]:
        """Everything the configured sources offer. Reads only."""
        import anyio

        from .setup import store

        rows = await anyio.to_thread.run_sync(lambda: store.catalogue(REPO_ROOT))
        return {"skills": rows, "sources": [s.repo for s in store.sources(REPO_ROOT)]}

    @app.post("/skills/review")
    async def review_skill(request: SkillInstall) -> dict[str, Any]:
        """Fetch and describe a skill without installing it."""
        import anyio

        from .setup import store

        return await anyio.to_thread.run_sync(
            lambda: store.review_remote(
                REPO_ROOT, request.repo, request.path, tool_registry
            )
        )

    @app.post("/skills/install")
    async def install_skill(request: SkillConfirm) -> dict[str, Any]:
        from .setup import store

        result = store.install_reviewed(request.staged)
        runtime_store.audit("setup", "skill-install", result)
        return result

    @app.delete("/skills/{name}")
    async def remove_skill(name: str) -> dict[str, Any]:
        from .setup import skills

        result = skills.remove(name)
        runtime_store.audit("setup", "skill-remove", result)
        return result

    @app.get("/paths")
    async def show_paths() -> dict[str, str]:
        return paths.describe()

    @app.get("/logs", response_model=LogPage)
    async def read_logs(subsystem: str = "errors", lines: int = 300) -> LogPage:
        """The tail of one log file.

        `errors` by default, because that is the file that answers the question
        people actually have. Already redacted on the way to disk, so there is
        nothing further to strip here.
        """
        return LogPage(
            subsystem=subsystem,
            lines=tail(subsystem, lines=max(1, min(lines, 2000))),
            available=available_logs(),
            directory=str(logs_dir()),
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
        changed: dict[str, Any] = {}
        if update.paused is not None:
            initiative.set_paused(update.paused)
            changed["paused"] = update.paused
        for field_name in (
            "quiet_start",
            "quiet_end",
            "cooldown_seconds",
            "daily_token_budget",
            "speak_when_away",
        ):
            value = getattr(update, field_name)
            if value is not None:
                setattr(initiative.mind.settings, field_name, value)
                changed[field_name] = value
        # Persisted the same way provider settings are, so a restart keeps them.
        provider_config.update(
            {
                f"MARVI_{key.upper()}": str(value)
                for key, value in changed.items()
                if key != "paused"
            }
        )
        runtime_store.audit("initiative", "mind", changed)
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

    async def _listening(base_url: str) -> bool:
        """Is anything accepting connections on this endpoint?

        A local provider is configured the moment it has a default URL, which
        made the page say CONNECTED for an Ollama that was not running. The
        endpoint is on this machine, so a TCP connect answers it in about a
        millisecond and needs no HTTP request against an unknown API shape.
        """
        parsed = urlparse(base_url)
        host, port = parsed.hostname, parsed.port
        if not host:
            return False
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=LOCAL_PROBE_TIMEOUT
            )
        except (TimeoutError, OSError):
            return False
        writer.close()
        with suppress(Exception):
            await writer.wait_closed()
        return True

    @app.get("/providers", response_model=ProviderPage)
    async def providers() -> ProviderPage:
        usage = provider_client.usage_by_provider()
        cooling = provider_client.cooldowns()
        # Probed together: a handful of dead endpoints in sequence is a
        # visible pause on a page the user opens to find out what is wrong.
        local = [p for p in all_profiles() if p.access_path == "local"]
        probes = await asyncio.gather(*(_listening(p.base_url()) for p in local))
        reachable = dict(zip((p.name for p in local), probes, strict=True))
        rows = [
            ProviderRow(
                name=p.name,
                label=p.label(),
                access_path=p.access_path,
                api_mode=p.api_mode,
                auth_type=p.auth_type,
                configured=p.configured(),
                base_url=p.base_url() or "",
                models={
                    "main": p.model_for("main"),
                    "aux": p.model_for("aux"),
                    "vision": p.default_vision_model or "",
                },
                env={
                    "key": p.key_env[0] if p.key_env else "",
                    "model": p.default_model_env or "",
                    "url": p.base_url_env or "",
                },
                limits={
                    "style": p.limits.style,
                    "windows": [list(w) for w in p.limits.windows],
                    "readable": p.limits.readable,
                    "note": p.limits.note,
                },
                usage=usage.get(p.name, {"input": 0, "output": 0, "cached_input": 0, "billable": 0}),
                cooldown=cooling.get(p.name),
                oauth=broker().status(p),
                # Shown before connecting, not after. See docs/PROVIDERS.md.
                warning=plan_warning(p),
                reachable=reachable.get(p.name),
            )
            for p in all_profiles()
        ]
        total = provider_client.usage()
        return ProviderPage(
            providers=rows,
            selected=os.environ.get("MARVI_PROVIDER", "").strip() or None,
            settings=provider_config.visible(),
            totals={
                "input": total.input,
                "output": total.output,
                "cached_input": total.cached_input,
                "billable": total.billable,
            },
        )

    @app.put("/providers/settings", response_model=ProviderPage)
    async def set_provider_settings(update: ProviderSettingsUpdate) -> ProviderPage:
        provider_config.update(update.values)
        # A key typed in a moment ago must not appear in the next log line.
        redactor().refresh()
        # Connecting a provider that was cooling down should retry it, not wait
        # out a cooldown earned by the credential the user just replaced.
        for name in list(provider_client.cooldowns()):
            provider_client.clear_cooldown(name)
        runtime_store.audit(
            "providers", "settings",
            # Never audit the values; several of them are credentials.
            {"changed": sorted(update.values)},
        )
        return await providers()

    @app.post("/providers/{name}/oauth/start", response_model=OAuthStart)
    async def start_oauth(name: str) -> OAuthStart:
        try:
            started = broker().start(name)
        except OAuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        runtime_store.audit("providers", "oauth-start", {"provider": name})
        return OAuthStart(url=started["url"], redirect_uri=started["redirect_uri"])

    @app.get("/providers/{name}/oauth/status")
    async def oauth_status(name: str) -> dict[str, Any]:
        """Poll the flow. Never blocks, and never returns the token itself."""
        return broker().poll(name)

    @app.post("/providers/{name}/disconnect", response_model=ProviderPage)
    async def disconnect_provider(name: str) -> ProviderPage:
        removed = broker().disconnect(name)
        # A key provider disconnects by clearing its credential instead.
        profile = next((p for p in all_profiles() if p.name == name), None)
        if profile is not None and profile.key_env:
            provider_config.update({profile.key_env[0]: ""})
        runtime_store.audit("providers", "disconnect", {"provider": name, "token": removed})
        return await providers()

    @app.get("/providers/voice", response_model=VoiceProvider)
    async def voice_provider() -> VoiceProvider:
        """Resolve the voice LLM for the Agent worker.

        The Agent runs in its own environment and must not carry its own copy of
        the provider table. It asks here, over the same loopback channel it
        already uses for tools, and gets whatever the user configured.
        """
        # The LiveKit OpenAI plugin speaks chat completions, and a local server
        # that is merely configured is not the same as one that is running.
        usable = [
            p
            for p in provider_client.candidates(
                os.environ.get("MARVI_PROVIDER", "").strip() or None
            )
            if p.api_mode == "chat_completions" and provider_client.reachable(p)
        ]
        if not usable:
            raise HTTPException(
                status_code=503, detail="no usable provider for the voice path"
            )
        chosen = usable[0]
        return VoiceProvider(
            provider=chosen.name,
            base_url=chosen.base_url() or "",
            model=chosen.model_for("main"),
            api_key=chosen.api_key() or "local",
        )

    @app.get("/identity", response_model=IdentityStatus)
    async def read_identity() -> IdentityStatus:
        loaded = identity.read()
        status = identity.status()
        return IdentityStatus(
            soul=loaded.soul,
            user=loaded.user,
            tokens=loaded.tokens,
            budget=int(status["budget"]),
            truncated=loaded.truncated,
            directory=str(status["directory"]),
        )

    @app.put("/identity", response_model=IdentityStatus)
    async def write_identity(update: IdentityUpdate) -> IdentityStatus:
        if update.soul is not None:
            identity.write_soul(update.soul)
        if update.user is not None:
            identity.write_user(update.user)
        runtime_store.audit(
            "identity", "write",
            {"soul": update.soul is not None, "user": update.user is not None},
        )
        return await read_identity()

    @app.get("/audit", response_model=AuditPage)
    async def audit_tail(limit: int = 100) -> AuditPage:
        return AuditPage(events=runtime_store.recent_audit(limit=max(1, min(limit, 500))))

    return app


app = create_app()
