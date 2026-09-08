"""Narrow browser control API and agent tool adapter."""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .tools import ToolSpec
from .localauth import guard


class StartBrowser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: str = "default"
    url: str = ""
    objective: str = Field(default="Browse", max_length=160)


class BrowserControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    command: Literal["pause", "private", "resume", "stop", "show", "close"]


class ProfileEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["create", "rename", "delete"]
    label: str = Field(default="", max_length=60)
    profile_id: str = ""


class ExportDownload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact: str
    destination: str


def browser_router(get_service, audit) -> APIRouter:
    router = APIRouter(prefix="/browser", dependencies=[Depends(guard)])

    async def call(function, *args):
        try:
            return await asyncio.to_thread(function, *args)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("")
    async def status():
        return await call(get_service().status)

    @router.post("/start")
    async def start(body: StartBrowser):
        audit("browser_control", "browser_start", {"profile_id": body.profile_id})
        return await call(get_service().start, body.profile_id, body.url, body.objective)

    @router.post("/profiles")
    async def profile(body: ProfileEdit):
        audit("browser_control", "browser_profile", {"action": body.action, "profile_id": body.profile_id})
        return await call(get_service().profile, body.action, body.label, body.profile_id)

    @router.post("/{session_id}/control")
    async def control(session_id: str, body: BrowserControl):
        audit("browser_control", "browser_control", {"session_id": session_id, "command": body.command})
        return await call(get_service().control, session_id, body.revision, body.command)

    @router.post("/{session_id}/download")
    async def export(session_id: str, body: ExportDownload):
        result = await call(get_service().export, session_id, body.artifact, body.destination)
        audit("browser_control", "browser_save_download", {"session_id": session_id})
        return result

    return router


def register_workspace_browser_tools(registry, get_service):
    def start(url: str = "", profile_id: str = "default", objective: str = "Browse"):
        return get_service().start(profile_id, url, objective)

    def action(session_id: str, revision: int, action: str, arguments: dict,
               action_id: str, request_confirmation: bool = False):
        return get_service().action(session_id, revision, action, arguments, action_id)

    def control(session_id: str, revision: int, command: str):
        return get_service().control(session_id, revision, command)

    registry.register(ToolSpec(
        name="browser_open", description="Open a visible saved browser profile for a user-requested task. Returns a receipt; read browser_status next.",
        arguments={}, optional={"url": str, "profile_id": str, "objective": str},
        sensitive=False, handler=start,
    ))
    registry.register(ToolSpec(
        name="browser_status", description="Read browser sessions, revisions, tabs and the last operation result. Wait until ready before acting. Private input hides observations.",
        arguments={}, sensitive=False, handler=lambda: get_service().status(),
    ))
    registry.register(ToolSpec(
        name="browser_action", description=(
            "Act in a ready browser session. Use its current revision and an exact tab_id. "
            "Actions: read, navigate, new_tab, click, fill, select, press, scroll, back, reload, "
            "close_tab, dialog, screenshot, upload. arguments contains tab_id and observed role/name "
            "or selector; url/text/value/key/pixels/path as needed. Never enter passwords or OTPs: "
            "use browser_control private and ask the user to sign in. Decide if approval is needed "
            "and set request_confirmation=true. Use a unique action_id; reuse it only for transport retries. "
            "Read browser_status to verify completion, never claim an accepted receipt is success."),
        arguments={"session_id": str, "revision": int, "action": str, "arguments": dict, "action_id": str},
        optional={"request_confirmation": bool}, sensitive=False,
        sensitive_when=lambda args: args.get("request_confirmation", False), handler=action,
    ))
    registry.register(ToolSpec(
        name="browser_control", description=(
            "Control the selected browser task: pause, private (ask the user for login in the website), "
            "resume (only after the user is done), stop, close, or show (only when the user asks). "
            "Use the latest revision. After resume, read a fresh observation before interacting."),
        arguments={"session_id": str, "revision": int, "command": str}, sensitive=False, handler=control,
    ))
    registry.register(ToolSpec(
        name="browser_save_download", description="Save a completed browser download to an allowed workspace path. Existing files are never replaced. Choose whether confirmation is needed.",
        arguments={"session_id": str, "artifact": str, "destination": str},
        optional={"request_confirmation": bool}, sensitive=False,
        sensitive_when=lambda args: args.get("request_confirmation", False),
        handler=lambda session_id, artifact, destination, request_confirmation=False: get_service().export(session_id, artifact, destination),
    ))
