"""Narrow browser control API and agent tool adapter."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .localauth import guard
from .tools import ToolSpec


class StartBrowser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: str = "default"
    url: str = ""
    objective: str = Field(default="Browse", max_length=160)


class BrowserHostRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str
    token: str


class BrowserUIAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    action: Literal["navigate", "new_tab", "close_tab", "back", "forward", "reload"]
    arguments: dict = Field(default_factory=dict)
    action_id: str = Field(min_length=1, max_length=64)


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


def browser_router(get_service, audit, activate=lambda: None) -> APIRouter:
    router = APIRouter(prefix="/browser", dependencies=[Depends(guard)])

    async def call(job: str, *args):
        """Run one workspace method on a worker thread.

        The method is *looked up* on the thread too. It used to be written as
        `call(get_service().status)`, which evaluates `get_service()` on the
        event loop -- and that takes `browser_lock` and, the first time,
        constructs the whole workspace there. Everything the loop owes anybody
        else waits behind it.
        """

        def run():
            return getattr(get_service(), job)(*args)

        try:
            return await asyncio.to_thread(run)
        except TimeoutError as exc:
            raise HTTPException(503, "Browser service is busy. Refresh its state before retrying.") from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("")
    async def status():
        return await call("status")

    @router.post("/host")
    async def host(body: BrowserHostRegistration):
        await call("register_host", body.endpoint, body.token)
        return {"ok": True}

    @router.post("/start")
    async def start(body: StartBrowser):
        audit("browser_control", "browser_start", {"profile_id": body.profile_id})
        result = await call("start", body.profile_id, body.url, body.objective)
        activate()
        return result

    @router.post("/profiles")
    async def profile(body: ProfileEdit):
        audit(
            "browser_control",
            "browser_profile",
            {"action": body.action, "profile_id": body.profile_id},
        )
        return await call("profile", body.action, body.label, body.profile_id)

    @router.post("/{session_id}/control")
    async def control(session_id: str, body: BrowserControl):
        audit(
            "browser_control",
            "browser_control",
            {"session_id": session_id, "command": body.command},
        )
        return await call("control", session_id, body.revision, body.command)

    @router.post("/{session_id}/action")
    async def action(session_id: str, body: BrowserUIAction):
        audit(
            "browser_control",
            "browser_navigation",
            {"session_id": session_id, "action": body.action},
        )
        return await call(
            "action",
            session_id,
            body.revision,
            body.action,
            body.arguments,
            body.action_id,
            True,
        )

    @router.post("/{session_id}/download")
    async def export(session_id: str, body: ExportDownload):
        result = await call("export", session_id, body.artifact, body.destination)
        audit("browser_control", "browser_save_download", {"session_id": session_id})
        return result

    return router


def register_workspace_browser_tools(registry, get_service, vision_client=None):
    def migrate(**_arguments):
        raise ValueError(
            "This legacy browser call was not executed. Read browser_status, then use browser_action or browser_control with the current session ID and revision."
        )

    # Retain resolvable names for stored prompts without allowing an old
    # approval to silently bind to whichever tab happens to be open now.
    for name, required, optional in (
        ("browser_read", {}, {}),
        ("browser_links", {}, {"limit": int}),
        ("browser_click", {"selector": str}, {}),
        ("browser_type", {"selector": str, "text": str}, {"submit": bool}),
        ("browser_back", {}, {}),
        ("browser_screenshot", {}, {"path": str}),
        ("browser_close", {}, {}),
    ):
        registry.register(
            ToolSpec(
                name=name,
                description="Legacy browser call: use browser_status then the session-aware browser_action/browser_control instead.",
                arguments=required,
                optional=optional,
                sensitive=False,
                handler=migrate,
            )
        )

    def read_image(session_id: str, revision: int, tab_id: str, question: str):
        import base64

        from . import auxiliary
        from .screen import MAX_OUTPUT_TOKENS, SYSTEM_PROMPT
        from .untrusted import wrap_external

        if vision_client is None:
            raise ValueError("Configure the Vision model before reading browser images")
        png = get_service().image(session_id, revision, tab_id)
        response = vision_client.call_with_fallback(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question[:2000]},
                        {
                            "type": "image",
                            "media_type": "image/png",
                            "data": base64.b64encode(png).decode("ascii"),
                        },
                    ],
                },
            ],
            job="vision",
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.2,
            **auxiliary.fallback_overrides("vision"),
        )
        return wrap_external("browser-vision", getattr(response, "text", "")).model_dump()

    registry.register(
        ToolSpec(
            name="browser_read_image",
            description="Answer a question about one browser tab using the configured Vision model. Editable fields are masked; unavailable during private input.",
            arguments={"session_id": str, "revision": int, "tab_id": str, "question": str},
            sensitive=False,
            handler=read_image,
        )
    )

    def start(url: str = "", profile_id: str = "default", objective: str = "Browse"):
        return get_service().start(profile_id, url, objective)

    def action(
        session_id: str,
        revision: int,
        action: str,
        arguments: dict,
        action_id: str,
        request_confirmation: bool = False,
    ):
        return get_service().action(session_id, revision, action, arguments, action_id)

    def control(session_id: str, revision: int, command: str):
        return get_service().control(session_id, revision, command)

    registry.register(
        ToolSpec(
            name="browser_open",
            description=(
                "Open a visible saved browser profile for a task the user asked for. Returns a "
                "receipt, not a browser: read browser_status until the state is ready before acting. "
                "One browser per profile -- if it refuses, it names the existing session, so use that "
                "one or close it. For a question the web can answer, search instead."
            ),
            arguments={},
            optional={"url": str, "profile_id": str, "objective": str},
            sensitive=False,
            handler=start,
        )
    )
    registry.register(
        ToolSpec(
            name="browser_status",
            description="Read browser sessions, revisions, tabs and the last operation result. Wait until ready before acting. Private input hides observations.",
            arguments={},
            sensitive=False,
            handler=lambda: get_service().status(),
        )
    )
    registry.register(
        ToolSpec(
            name="browser_action",
            description=(
                "Act in a ready browser session. Use its current revision and an exact tab_id. "
                "Actions: read, navigate, new_tab, click, fill, select, press, scroll, back, forward, reload, "
                "close_tab, dialog, screenshot, upload. arguments contains tab_id and observed role/name "
                "or selector; url/text/value/key/pixels/path as needed. Never enter passwords or OTPs: "
                "use browser_control private and ask the user to sign in. Decide if approval is needed "
                "and set request_confirmation=true. Use a unique action_id; reuse it only for transport retries. "
                "Read browser_status to verify completion, never claim an accepted receipt is success."
            ),
            arguments={
                "session_id": str,
                "revision": int,
                "action": str,
                "arguments": dict,
                "action_id": str,
            },
            optional={"request_confirmation": bool},
            sensitive=False,
            sensitive_when=lambda args: args.get("request_confirmation", False),
            handler=action,
        )
    )
    registry.register(
        ToolSpec(
            name="browser_control",
            description=(
                "Control the selected browser task: pause, private (ask the user for login in the website), "
                "resume (only after the user is done), stop, close, or show (only when the user asks). "
                "Use the latest revision. After resume, read a fresh observation before interacting."
            ),
            arguments={"session_id": str, "revision": int, "command": str},
            sensitive=False,
            handler=control,
        )
    )
    registry.register(
        ToolSpec(
            name="browser_save_download",
            description="Save a completed browser download to an allowed workspace path. Existing files are never replaced. Choose whether confirmation is needed.",
            arguments={"session_id": str, "artifact": str, "destination": str},
            optional={"request_confirmation": bool},
            sensitive=False,
            sensitive_when=lambda args: args.get("request_confirmation", False),
            handler=lambda session_id, artifact, destination, request_confirmation=False: (
                get_service().export(session_id, artifact, destination)
            ),
        )
    )
