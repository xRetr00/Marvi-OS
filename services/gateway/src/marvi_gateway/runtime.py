from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_urlsafe
from typing import Any, Literal

from pydantic import BaseModel, Field

AssistantPhase = Literal[
    "ready",
    "wake",
    "listening",
    "thinking",
    "speaking",
    "action",
    "notification",
    "confirmation",
    "error",
]

CONFIRMATION_TTL_SECONDS = 120.0
AUDIT_TAIL_LIMIT = 200
ROOM_EVENT_TTL_SECONDS = 25.0


def default_audit_path() -> Path:
    configured = os.environ.get("MARVI_AUDIT_LOG")
    if configured:
        return Path(configured)
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(root) / "Marvi OS" / "audit.jsonl"


class ComponentStatus(BaseModel):
    state: Literal["ready", "starting", "pending", "offline", "error"]
    detail: str


class ConfirmationRequest(BaseModel):
    token: str
    action: str
    detail: str
    tool: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)


class RoomEvent(BaseModel):
    id: int
    at: str
    type: str
    summary: str


class AssistantState(BaseModel):
    phase: AssistantPhase = "ready"
    caption: str = "Say Marvi"
    detail: str | None = None
    level: float = Field(default=0.0, ge=0.0, le=1.0)
    yolo: bool = False
    microphone: bool = True
    camera: bool = True
    confirmation: ConfirmationRequest | None = None
    # A background room event rides its own channel so it can never take over a
    # live voice phase. The Island shows it only while idle.
    room_event: RoomEvent | None = None


class RuntimeStatus(BaseModel):
    product: str = "Marvi OS"
    version: str
    state: Literal["ready", "starting", "degraded", "offline", "error"]
    components: dict[str, ComponentStatus]
    assistant: AssistantState


class ModeUpdate(BaseModel):
    yolo: bool


class ConfirmationDecision(BaseModel):
    decision: Literal["approve", "deny"]
    arguments: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(BaseModel):
    at: str
    event: str
    tool: str
    arguments: dict[str, Any]
    mode: Literal["confirm", "yolo"]
    detail: str | None = None


class AuditPage(BaseModel):
    events: list[AuditEvent]


class TokenRejectedError(Exception):
    """The supplied confirmation token is unknown, spent, or expired."""


class ArgumentsMutatedError(Exception):
    """The approval did not match the arguments the token was issued for."""


def canonical_arguments(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)


class PendingConfirmation:
    __slots__ = ("arguments", "fingerprint", "issued_at", "token", "tool")

    def __init__(self, token: str, tool: str, arguments: dict[str, Any], issued_at: float):
        self.token = token
        self.tool = tool
        self.arguments = arguments
        self.fingerprint = canonical_arguments(arguments)
        self.issued_at = issued_at


class RuntimeStore:
    def __init__(self, audit_path: Path | None = None) -> None:
        self.assistant = AssistantState()
        self.audit_path = audit_path or default_audit_path()
        self._pending: dict[str, PendingConfirmation] = {}
        self._last_room_event_id: int | None = None
        self._room_event_at: float | None = None

    # -- mode ---------------------------------------------------------------

    def set_yolo(self, enabled: bool) -> AssistantState:
        self.assistant = self.assistant.model_copy(update={"yolo": enabled})
        return self.assistant

    @property
    def mode(self) -> Literal["confirm", "yolo"]:
        return "yolo" if self.assistant.yolo else "confirm"

    # -- audit --------------------------------------------------------------

    def audit(
        self,
        event: str,
        tool: str,
        arguments: dict[str, Any],
        detail: str | None = None,
    ) -> None:
        """Append one immutable line. Auditing never blocks the action path."""
        record = AuditEvent(
            at=datetime.now(UTC).isoformat(),
            event=event,
            tool=tool,
            arguments=arguments,
            mode=self.mode,
            detail=detail,
        )
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
        except OSError:
            # ponytail: a failed write must not swallow the user's action.
            # Upgrade to a queued writer only if disk errors are ever observed.
            pass

    def recent_audit(self, limit: int = AUDIT_TAIL_LIMIT) -> list[AuditEvent]:
        try:
            lines = self.audit_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        events: list[AuditEvent] = []
        for line in reversed(lines):
            if len(events) >= limit:
                break
            try:
                events.append(AuditEvent.model_validate_json(line))
            except ValueError:
                continue
        return events

    # -- background room events ---------------------------------------------

    def observe_room_event(self, event: dict[str, Any] | None, now: float | None = None) -> None:
        """Surface a new background event briefly, then let it expire.

        Never touches `phase`: a room event must not interrupt or overwrite a
        live voice turn, and it must not pull focus.
        """
        moment = now if now is not None else time.monotonic()

        if event is not None:
            try:
                identifier = int(event["id"])
            except (KeyError, TypeError, ValueError):
                identifier = None
            if identifier is not None and self._last_room_event_id is None:
                # First observation only establishes a baseline. Whatever was
                # already in the log happened before we were running, and must
                # not flash on the Island at startup.
                self._last_room_event_id = identifier
                return
            if identifier is not None and identifier != self._last_room_event_id:
                self._last_room_event_id = identifier
                self._room_event_at = moment
                self.assistant = self.assistant.model_copy(
                    update={
                        "room_event": RoomEvent(
                            id=identifier,
                            at=str(event.get("at", "")),
                            type=str(event.get("type", "")),
                            summary=str(event.get("summary") or event.get("type") or "room event"),
                        )
                    }
                )
                return

        if (
            self.assistant.room_event is not None
            and self._room_event_at is not None
            and moment - self._room_event_at >= ROOM_EVENT_TTL_SECONDS
        ):
            self._room_event_at = None
            self.assistant = self.assistant.model_copy(update={"room_event": None})

    # -- confirmation tokens ------------------------------------------------

    def issue_confirmation(
        self, tool: str, arguments: dict[str, Any], action: str, detail: str
    ) -> ConfirmationRequest:
        self.expire_confirmations()
        token = token_urlsafe(24)
        self._pending[token] = PendingConfirmation(
            token=token, tool=tool, arguments=dict(arguments), issued_at=time.monotonic()
        )
        request = ConfirmationRequest(
            token=token, action=action, detail=detail, tool=tool, arguments=dict(arguments)
        )
        self.assistant = self.assistant.model_copy(
            update={
                "phase": "confirmation",
                "caption": action,
                "detail": detail,
                "confirmation": request,
            }
        )
        return request

    def pending_issued_at(self, token: str) -> float:
        return self._pending[token].issued_at

    def expire_confirmations(self, now: float | None = None) -> None:
        cutoff = (now if now is not None else time.monotonic()) - CONFIRMATION_TTL_SECONDS
        expired = [
            token
            for token, pending in self._pending.items()
            if pending.issued_at < cutoff
        ]
        for token in expired:
            pending = self._pending.pop(token)
            self.audit("expired", pending.tool, pending.arguments)
            self._clear_confirmation(token, caption="Confirmation expired", action=pending.tool)

    def take_confirmation(
        self, token: str, arguments: dict[str, Any]
    ) -> PendingConfirmation:
        """Consume a token exactly once, only for the arguments it was issued for."""
        self.expire_confirmations()
        pending = self._pending.pop(token, None)
        if pending is None:
            raise TokenRejectedError(token)
        if canonical_arguments(arguments) != pending.fingerprint:
            # The token is burned either way: a mismatch means the request the
            # user saw is not the request being approved.
            self.audit("argument_mismatch", pending.tool, arguments, detail="token burned")
            self._clear_confirmation(token, caption="Action blocked", action=pending.tool)
            raise ArgumentsMutatedError(token)
        return pending

    def settle_confirmation(self, token: str, caption: str, action: str) -> AssistantState:
        return self._clear_confirmation(token, caption=caption, action=action)

    def _clear_confirmation(self, token: str, caption: str, action: str) -> AssistantState:
        current = self.assistant.confirmation
        if current is not None and current.token != token:
            return self.assistant
        self.assistant = self.assistant.model_copy(
            update={
                "phase": "notification",
                "caption": caption,
                "detail": action,
                "confirmation": None,
            }
        )
        return self.assistant
