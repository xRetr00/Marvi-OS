from __future__ import annotations

from typing import Literal

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


class ComponentStatus(BaseModel):
    state: Literal["ready", "starting", "pending", "offline", "error"]
    detail: str


class ConfirmationRequest(BaseModel):
    token: str
    action: str
    detail: str


class AssistantState(BaseModel):
    phase: AssistantPhase = "ready"
    caption: str = "Say Marvi"
    detail: str | None = None
    level: float = Field(default=0.0, ge=0.0, le=1.0)
    yolo: bool = False
    microphone: bool = True
    camera: bool = True
    confirmation: ConfirmationRequest | None = None


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


class RuntimeStore:
    def __init__(self) -> None:
        self.assistant = AssistantState()

    def set_yolo(self, enabled: bool) -> AssistantState:
        self.assistant = self.assistant.model_copy(update={"yolo": enabled})
        return self.assistant

    def resolve_confirmation(self, token: str, decision: str) -> AssistantState | None:
        request = self.assistant.confirmation
        if request is None or request.token != token:
            return None

        caption = "Action approved" if decision == "approve" else "Action denied"
        self.assistant = self.assistant.model_copy(
            update={
                "phase": "notification",
                "caption": caption,
                "detail": request.action,
                "confirmation": None,
            }
        )
        return self.assistant
