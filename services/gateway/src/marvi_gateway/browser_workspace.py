"""Visible Chromium workspaces. Playwright owns the browser protocol.

Gateway owns task state and serialization; Electron supervises the Gateway
process tree. No arbitrary Python/JS/CDP is exposed to the model. Browser profile
contents never enter this metadata store or the tool response.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from .background import LoopThread
from .browser_privacy import capture_barrier
from .logs import get_logger
from .paths import root
from .untrusted import wrap_external
from .web import assert_public_http_url

#: How long private input waits for in-flight reads before giving up.
#:
#: Under the 60s ceiling on `control`, so the caller hears a real answer
#: instead of a timeout with the barrier left closed behind it.
PRIVATE_WAIT_SECONDS = 30.0

MAX_FILE = 100 * 1024 * 1024
MAX_TASK_FILES = 500 * 1024 * 1024
ACTIVE = {"starting", "running", "resuming"}
log = get_logger("browser")


def safe_url(url: str) -> str:
    """No query, fragment, or URL credentials in status/audit metadata."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", ""))


class BrowserWorkspace:
    def __init__(
        self,
        directory: Path | None = None,
        *,
        headless: bool = False,
        workspace=None,
        allowed_origins: tuple[str, ...] = (),
    ):
        self.directory = directory or root() / "browser"
        self.directory.mkdir(parents=True, exist_ok=True)
        artifacts = self.directory / "artifacts"
        if artifacts.exists():
            for artifact in artifacts.iterdir():
                if artifact.is_file() and artifact.stat().st_mtime < time.time() - 86400:
                    artifact.unlink()
        self.headless = headless  # Injection for tests, never model-controlled.
        self.workspace = workspace
        self.allowed_origins = allowed_origins  # Test fixture origins only.
        self._db = sqlite3.connect(self.directory / "metadata.sqlite3", check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, body TEXT)")
        row = self._db.execute("SELECT body FROM state WHERE id=1").fetchone()
        self.profiles = (
            json.loads(row[0])["profiles"] if row else [{"id": "default", "label": "Personal"}]
        )
        self.sessions: dict[str, dict] = {}
        if row:
            for item in json.loads(row[0]).get("sessions", []):
                item.update(
                    state="closed",
                    detail="Browser stopped. Open the profile to continue.",
                    result=None,
                )
                self.sessions[item["id"]] = item
        self._contexts: dict[str, Any] = {}
        self._host: dict[str, str] | None = None
        self._embedded: dict[str, Any] = {}
        self._pages: dict[str, dict[str, Any]] = {}
        self._operations: dict[str, asyncio.Task] = {}
        self._receipts: dict[str, dict] = {}
        self._dialogs: dict[str, Any] = {}
        self._downloads: set[asyncio.Task] = set()
        self._playwright = None
        self._network = None
        self._last_expiry = 0.0
        self._launch_lock = asyncio.Lock()
        self._loop = LoopThread("marvi-browser-workspace")
        self._save()

    def register_host(self, endpoint: str, token: str):
        if not re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", endpoint) or len(token) != 64:
            raise ValueError("Invalid desktop browser host")

        async def register():
            self._host = {"endpoint": endpoint, "token": token}

        self._loop.submit(register(), timeout=3)

    async def _host_request(self, path: str, body: dict):
        import httpx

        if self._host is None:
            raise ValueError("Desktop browser host is unavailable")
        async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
            response = await client.post(
                self._host["endpoint"] + path,
                json=body,
                headers={"Authorization": "Bearer " + self._host["token"]},
            )
            response.raise_for_status()
            return response.json()

    def _save(self):
        # Page content and results are deliberately ephemeral.
        body = {
            "profiles": self.profiles,
            "sessions": [
                {k: v for k, v in s.items() if k not in {"result", "tabs"}}
                for s in self.sessions.values()
            ],
        }
        self._db.execute("INSERT OR REPLACE INTO state VALUES (1, ?)", (json.dumps(body),))
        self._db.commit()

    def _session(self, sid: str) -> dict:
        if sid not in self.sessions:
            raise ValueError("Unknown browser session")
        return self.sessions[sid]

    def _check(self, sid: str, revision: int) -> dict:
        session = self._session(sid)
        if session["revision"] != revision:
            raise ValueError("Browser state changed. Read browser_status before acting.")
        return session

    def _change(self, session, state: str, detail: str):
        session.update(state=state, detail=detail, revision=session["revision"] + 1)
        self._save()
        log.info("session=%s state=%s revision=%s", session["id"], state, session["revision"])

    def _public(self, session):
        data = dict(session)
        if session["state"] in {"private", "stopping"} or capture_barrier.blocked:
            data.update(result=None, tabs=[])
            data.pop("download", None)
            data.pop("downloads", None)
        return data

    def status(self) -> dict:
        async def read():
            if time.monotonic() - self._last_expiry > 60:
                self._last_expiry = time.monotonic()
                for artifact in (self.directory / "artifacts").glob("*"):
                    if artifact.is_file() and artifact.stat().st_mtime < time.time() - 86400:
                        artifact.unlink()
            for sid in list(self._contexts):
                await self._tabs(sid)
            return {
                "available": True,
                "driver": "electron-playwright" if self._host else "playwright",
                "profiles": list(self.profiles),
                "sessions": [self._public(s) for s in self.sessions.values()],
                "private_input": capture_barrier.blocked,
            }

        return self._loop.submit(read(), timeout=3)

    def profile(self, action: str, label: str = "", profile_id: str = "") -> dict:
        async def edit():
            if action == "create":
                if not label.strip() or len(label) > 60:
                    raise ValueError("Profile name must contain 1-60 characters")
                self.profiles.append({"id": uuid4().hex, "label": label.strip()})
            else:
                profile = next((p for p in self.profiles if p["id"] == profile_id), None)
                if profile is None:
                    raise ValueError("Unknown profile")
                if action == "rename":
                    if not label.strip() or len(label) > 60:
                        raise ValueError("Profile name must contain 1-60 characters")
                    profile["label"] = label.strip()
                elif action == "delete":
                    if profile_id == "default":
                        raise ValueError("The default profile cannot be deleted")
                    if any(
                        s["profile_id"] == profile_id
                        and (s["id"] in self._contexts or s["state"] in ACTIVE)
                        for s in self.sessions.values()
                    ):
                        raise ValueError("Close this profile's browser before removing it")
                    if (self.directory / "electron-profiles" / profile_id).exists() or (self.directory / "passwords" / (profile_id + ".encrypted")).exists():
                        await self._host_request("/profile/delete", {"profile": profile_id})
                    target = (self.directory / "profiles" / profile_id).resolve()
                    if target.parent != (self.directory / "profiles").resolve():
                        raise ValueError("Invalid profile directory")
                    if target.exists():
                        shutil.rmtree(target)
                    self.profiles.remove(profile)
                else:
                    raise ValueError("Unknown profile action")
            self._save()
            return {"profiles": list(self.profiles)}

        return self._loop.submit(edit())

    def _url(self, url: str):
        p = urlsplit(url)
        if p.username or p.password:
            raise ValueError("URL credentials are not supported")
        origin = f"{p.scheme}://{p.netloc}"
        if origin in self.allowed_origins:
            return
        assert_public_http_url(url)

    async def _route(self, route):
        # Initial request guard for actionable errors. The separate upstream
        # proxy checks every connection, including redirect destinations.
        try:
            await asyncio.to_thread(self._url, route.request.url)
        except Exception:
            with contextlib.suppress(Exception):
                await route.abort("blockedbyclient")
        else:
            await route.continue_()

    def start(self, profile_id: str = "default", url: str = "", objective: str = "Browse") -> dict:
        async def begin():
            if capture_barrier.blocked:
                raise ValueError("Private input is active; resume before opening another browser")
            if not any(p["id"] == profile_id for p in self.profiles):
                raise ValueError("Unknown profile")
            # Already open is the commonest case, not an error.
            #
            # This refused with "This profile already has a browser. Select its
            # existing session." -- which is true, and useless to a model that
            # has just been asked to open a browser and now has to work out
            # which of its other tools finds the session it was not given the
            # id of. It failed that way twice in one session and burned tool
            # steps guessing.
            #
            # Handing back the session it would have had to go and find is the
            # same outcome with none of the detour.
            # One browser per profile, and the refusal says which one.
            #
            # The rule is real: a persistent profile is a directory on disk and
            # a second context on the same directory is how a profile gets
            # corrupted. `test_persistent_profile_actual_actions_and_isolation`
            # asserts it, and it is right to.
            #
            # What was wrong was the message. "This profile already has a
            # browser. Select its existing session." is true and unusable: the
            # model has just been told a session exists and not which one, so
            # it goes looking -- and in a real turn it spent its remaining tool
            # steps doing exactly that, then wrote a tool call as prose when
            # the budget ran out.
            #
            # The id costs nothing to include and turns a dead end into the
            # next call.
            if existing := next(
                (
                    one
                    for one in self.sessions.values()
                    if one["profile_id"] == profile_id
                    and (one["id"] in self._contexts or one["state"] in ACTIVE)
                ),
                None,
            ):
                raise ValueError(
                    "This profile already has a browser: session "
                    f"{existing['id']} ({existing['state']}). Use it, or close "
                    "it first."
                )
            sid = uuid4().hex
            session = {
                "id": sid,
                "profile_id": profile_id,
                "objective": objective[:160],
                "state": "starting",
                "revision": 0,
                "detail": "Opening browser",
                "tabs": [],
                "result": None,
            }
            self.sessions[sid] = session
            self._save()
            self._operations[sid] = asyncio.create_task(self._launch(sid, url))
            return self._public(session)

        return self._loop.submit(begin(), timeout=3)

    async def _launch(self, sid: str, url: str):
        session = self._session(sid)
        stage = "validate_url"
        host_requested = False
        try:
            if url:
                await asyncio.to_thread(self._url, url)
            async with self._launch_lock:
                stage = "start_dependencies"
                if self._network is None:
                    from .browser_network import BrowserNetwork

                    self._network = await asyncio.to_thread(BrowserNetwork, self.allowed_origins)
                if self._playwright is None:
                    from playwright.async_api import async_playwright

                    self._playwright = await async_playwright().start()
            transfer_dir = self.directory / "transfers" / sid
            transfer_dir.mkdir(parents=True, exist_ok=True)
            if self._host and not self.headless:
                stage = "open_embedded_host"
                host_requested = True
                host = await self._host_request(
                    "/open",
                    {
                        "id": sid,
                        "profile": session["profile_id"],
                        "proxy": self._network.settings,
                    },
                )
                stage = "connect_embedded_protocol"
                browser = await self._playwright.chromium.connect_over_cdp(
                    host["endpoint"],
                    headers={"Authorization": "Bearer " + self._host["token"]},
                    is_local=True,
                    artifacts_dir=host["downloads"],
                    timeout=30_000,
                )
                self._embedded[sid] = browser
                session["host"] = "embedded"
                context = browser.contexts[0]
                context.on("close", lambda: self._embedded.pop(sid, None))
                launching = asyncio.create_task(asyncio.sleep(0, result=context))
            else:
                if os.environ.get("MARVI_BROWSER_HOST_REQUIRED") == "1" and not self.headless:
                    raise ValueError("Desktop browser host is unavailable")
                session["host"] = "native"
                launching = asyncio.create_task(self._native_context(session, transfer_dir))
            try:
                context = await asyncio.shield(launching)
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    context = await launching
                    await context.close()
                raise
            self._contexts[sid] = context
            stage = "install_browser_routes"
            self._pages[sid] = {}
            context.set_default_timeout(10_000)
            await context.route("**/*", self._route)
            await context.route_web_socket("**/*", lambda ws: ws.close())
            context.on("page", lambda p: self._adopt(sid, p))
            context.on("close", lambda: self._closed(sid))
            for page in context.pages:
                self._adopt(sid, page)
            page = context.pages[0] if context.pages else await context.new_page()
            if url:
                stage = "initial_navigation"
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            if session["state"] == "stopping" or capture_barrier.blocked:
                return
            self._change(
                session, "ready", "Browser ready. You can browse or ask Marvi to work here."
            )
            await self._tabs(sid)
        except asyncio.CancelledError:
            if sid in self._contexts:
                await self._contexts[sid].close()
            if host_requested:
                with contextlib.suppress(Exception):
                    await self._host_request("/close", {"id": sid})
            raise
        except Exception as exc:
            session["error_type"] = type(exc).__name__
            session["error_stage"] = stage
            log.warning("session=%s launch_failed stage=%s error_type=%s", sid, stage, type(exc).__name__)
            if host_requested:
                with contextlib.suppress(Exception):
                    await self._host_request("/close", {"id": sid})
            self._change(
                session,
                "failed",
                "Browser could not open. Check the desktop host, engine and profile lock.",
            )

    async def _native_context(self, session, transfer_dir):
        return await self._playwright.chromium.launch_persistent_context(
            str(self.directory / "profiles" / session["profile_id"]),
            headless=self.headless,
            proxy=self._network.settings,
            args=[
                "--proxy-bypass-list=<-loopback>",
                "--disable-quic",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            ],
            accept_downloads=True,
            service_workers="block",
            downloads_path=str(transfer_dir),
            no_viewport=True,
            timeout=60_000,
        )

    def _adopt(self, sid, page):
        if page in self._pages[sid].values():
            return
        tid = uuid4().hex
        self._pages[sid][tid] = page
        page.on("dialog", lambda d: self._dialog(sid, tid, d))

        def downloading(download):
            task = asyncio.create_task(self._download(sid, download))
            self._downloads.add(task)
            task.add_done_callback(self._downloads.discard)

        page.on("download", downloading)
        page.on("framenavigated", lambda f: self._navigated(sid, page, f))
        page.on("close", lambda: self._pages.get(sid, {}).pop(tid, None))

    def _navigated(self, sid, page, frame):
        if frame == page.main_frame and sid in self.sessions:
            session = self.sessions[sid]
            session["revision"] += 1
            if session["state"] == "ready":
                self._change(session, "paused", "Page changed. Resume after checking the browser.")

    def _dialog(self, sid, tid, dialog):
        # Do not record website-provided dialog messages (may contain secrets).
        self._dialogs[sid] = dialog
        self.sessions[sid]["detail"] = (
            "Website dialog pending. Respond in the browser or use the dialog action."
        )

    async def _tabs(self, sid):
        session = self._session(sid)
        if session["state"] == "private" or capture_barrier.blocked:
            return []
        result = []
        for tid, page in list(self._pages.get(sid, {}).items()):
            if not page.is_closed():
                item = {"id": tid, "url": safe_url(page.url)}
                if sid in self._embedded:
                    # Host target identity is presentation metadata, never a global CDP capability.
                    previous = next(
                        (tab for tab in session.get("tabs", []) if tab["id"] == tid), {}
                    )
                    if previous.get("target"):
                        item["target"] = previous["target"]
                    else:
                        cdp = await self._contexts[sid].new_cdp_session(page)
                        try:
                            item["target"] = (await cdp.send("Target.getTargetInfo"))["targetInfo"][
                                "targetId"
                            ]
                        finally:
                            await cdp.detach()
                result.append(item)
        session["tabs"] = result
        return result

    def _closed(self, sid):
        self._contexts.pop(sid, None)
        self._pages.pop(sid, None)
        capture_barrier.leave(sid)
        self._change(self._session(sid), "closed", "Browser closed. Profile data is saved.")

    def action(self, sid: str, revision: int, action: str, arguments: dict, action_id: str, manual: bool = False) -> dict:
        async def enqueue():
            key = f"{sid}:{action_id}"
            signature = hashlib.sha256(
                json.dumps([revision, action, arguments], sort_keys=True).encode()
            ).hexdigest()
            if key in self._receipts:
                if self._receipts[key]["signature"] != signature:
                    raise ValueError("Action ID was already used with different arguments")
                return self._receipts[key]["receipt"]
            session = self._check(sid, revision)
            if session["state"] != "ready" and not (manual and session["state"] in {"paused", "cancelled"}):
                raise ValueError(
                    "Browser is not ready. Resume it or wait for the current operation."
                )
            if capture_barrier.blocked:
                raise ValueError("Private input is active; browser automation is paused")
            if action not in {
                "read",
                "navigate",
                "new_tab",
                "click",
                "fill",
                "select",
                "press",
                "scroll",
                "back",
                "forward",
                "reload",
                "close_tab",
                "dialog",
                "screenshot",
                "upload",
            }:
                raise ValueError("Unsupported browser action")
            finish_state = "paused" if manual and session["state"] != "ready" else "ready"
            self._change(session, "running", f"Browser: {action}")
            session["result"] = None
            session.pop("error_type", None)
            receipt = {
                "session_id": sid,
                "action_id": action_id,
                "status": "accepted",
                "instruction": "Read browser_status for completion before another action.",
            }
            self._receipts[key] = {"signature": signature, "receipt": receipt}
            if len(self._receipts) > 1024:
                self._receipts.pop(next(iter(self._receipts)))
            self._operations[sid] = asyncio.create_task(self._act(sid, action, dict(arguments), finish_state))
            return receipt

        return self._loop.submit(enqueue(), timeout=3)

    async def _act(self, sid, action, args, finish_state="ready"):
        session = self._session(sid)
        try:
            pages = self._pages[sid]
            tid = args.get("tab_id")
            if tid not in pages:
                if len(pages) != 1 or tid:
                    raise ValueError("Select an exact tab ID from browser_status")
                tid = next(iter(pages))
            page = pages[tid]
            session["active_tab"] = tid
            target = page
            if args.get("frame_url"):
                frames = [f for f in page.frames if f.url == args["frame_url"]]
                if len(frames) != 1:
                    raise ValueError("Select an unambiguous frame URL")
                target = frames[0]
            selector = args.get("selector", "")
            locator = target.locator(selector) if selector else None
            if args.get("role"):
                locator = target.get_by_role(args["role"], name=args.get("name", ""), exact=True)
            if action in {"navigate", "new_tab"}:
                destination = args.get("url", "")
                if action == "new_tab" and not destination:
                    destination = "about:blank"
                if destination != "about:blank" or action != "new_tab":
                    await asyncio.to_thread(self._url, destination)
                if action == "new_tab":
                    page = await self._contexts[sid].new_page()
                    self._adopt(sid, page)
                    tid = next(
                        key for key, candidate in self._pages[sid].items() if candidate == page
                    )
                    session["active_tab"] = tid
                await page.goto(destination, wait_until="domcontentloaded", timeout=30_000)
            elif action in {"click", "fill", "select", "upload"}:
                if locator is None or await locator.count() != 1:
                    raise ValueError("Use an unambiguous observed role/name or selector")
                if action == "click":
                    await locator.click()
                elif action == "fill":
                    if await locator.get_attribute(
                        "type"
                    ) == "password" or await locator.get_attribute("autocomplete") in {
                        "one-time-code",
                        "current-password",
                        "new-password",
                    }:
                        raise ValueError(
                            "Use Private input to enter credentials directly in the browser"
                        )
                    await locator.fill(str(args.get("text", "")))
                elif action == "select":
                    await locator.select_option(str(args["value"]))
                else:
                    if self.workspace is None:
                        raise ValueError("Configure a workspace before uploading")
                    file = self.workspace.resolve(str(args["path"]))
                    if not file.is_file() or file.stat().st_size > MAX_FILE:
                        raise ValueError("Upload must be a file under 100 MB")
                    await locator.set_input_files(str(file))
            elif action == "press":
                await page.keyboard.press(str(args["key"]))
            elif action == "scroll":
                await page.mouse.wheel(0, max(-2000, min(2000, int(args.get("pixels", 600)))))
            elif action == "back":
                await page.go_back(wait_until="domcontentloaded")
            elif action == "forward":
                # Every browser has one and this did not, so the toolbar could
                # go back and then had no way to undo that.
                await page.go_forward(wait_until="domcontentloaded")
            elif action == "reload":
                await page.reload(wait_until="domcontentloaded")
            elif action == "close_tab":
                await page.close()
            elif action == "dialog":
                dialog = self._dialogs.pop(sid, None)
                if dialog is None:
                    raise ValueError("No dialog is pending")
                if args.get("accept", False):
                    await dialog.accept()
                else:
                    await dialog.dismiss()
            elif action == "screenshot":
                dest = self.directory / "artifacts" / (uuid4().hex + ".png")
                dest.parent.mkdir(exist_ok=True)
                await page.screenshot(
                    path=str(dest), mask=[page.locator('input, textarea, [contenteditable="true"]')]
                )
                session["result"] = {"artifact": dest.name}
            if (
                sid not in self._contexts
                or session["state"] == "stopping"
                or capture_barrier.blocked
            ):
                session["result"] = None
                return
            if action != "screenshot" and not page.is_closed():
                text = await page.locator("body").aria_snapshot(timeout=5000)
                if session["state"] == "stopping" or capture_barrier.blocked:
                    return
                # No editable-field values in model observations.
                text = re.sub(r"(?m)^(\s*- (?:textbox|searchbox).*?):.*$", r"\1", text)
                session["result"] = wrap_external(
                    "browser",
                    {
                        "tab_id": tid,
                        "url": safe_url(page.url),
                        "snapshot": text[:12000],
                        "truncated": len(text) > 12000,
                    },
                ).model_dump()
            self._change(
                session, finish_state, "Action finished. Verify the observation before continuing."
            )
            await self._tabs(sid)
        except asyncio.CancelledError:
            session["result"] = None
            raise
        except Exception as exc:
            # Upstream errors can include selectors, input values and page text.
            log.warning("session=%s action_failed action=%s error_type=%s", sid, action, type(exc).__name__)
            session["result"] = None
            if session["state"] == "stopping":
                return
            self._change(
                session,
                "paused",
                "Action could not be verified. Inspect the browser before retrying.",
            )
            session["error_type"] = type(exc).__name__

    async def _download(self, sid, download):
        # An explicit download is staged; it never chooses its final host path.
        # Chromium reports a navigation-to-attachment as ERR_ABORTED before
        # its download event is delivered. That pauses the action, but must
        # not discard the file which is the successful navigation outcome.
        if capture_barrier.blocked or self.sessions[sid]["state"] not in {
            "ready",
            "running",
            "paused",
        }:
            await download.cancel()
            return
        destination = self.directory / "artifacts" / (uuid4().hex + ".download")
        destination.parent.mkdir(exist_ok=True)
        saving = None
        try:
            saving = asyncio.create_task(download.save_as(str(destination)))
            while not saving.done():
                sizes = [
                    p.stat().st_size
                    for p in (self.directory / "transfers" / sid).glob("*")
                    if p.is_file()
                ]
                if any(size > MAX_FILE for size in sizes) or sum(sizes) > MAX_TASK_FILES:
                    await download.cancel()
                    raise ValueError("Download quota exceeded")
                await asyncio.sleep(0.1)
            await saving
            used = self.sessions[sid].get("download_bytes", 0)
            if (
                destination.stat().st_size > MAX_FILE
                or used + destination.stat().st_size > MAX_TASK_FILES
            ):
                destination.unlink()
                raise ValueError("Download quota exceeded")
            with destination.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            self.sessions[sid]["download"] = {
                "artifact": destination.name,
                "bytes": destination.stat().st_size,
                "sha256": digest,
                "name": Path(download.suggested_filename).name[:120],
            }
            self.sessions[sid]["download_bytes"] = used + destination.stat().st_size
            self.sessions[sid].setdefault("downloads", []).append(self.sessions[sid]["download"])
            await download.delete()
        except asyncio.CancelledError:
            await download.cancel()
            destination.unlink(missing_ok=True)
            raise
        except Exception as exc:
            destination.unlink(missing_ok=True)
            self.sessions[sid]["download_error_type"] = type(exc).__name__
        finally:
            if saving and not saving.done():
                saving.cancel()
                await asyncio.gather(saving, return_exceptions=True)

    def export(self, sid: str, artifact: str, destination: str) -> dict:
        """Publish a completed file without replacing an existing destination."""

        async def save():
            session = self._session(sid)
            if capture_barrier.blocked:
                raise ValueError("Private input is active")
            item = next(
                (
                    item
                    for item in session.get("downloads", [session.get("download")])
                    if item and item["artifact"] == artifact
                ),
                None,
            )
            if not item or item["artifact"] != artifact:
                raise ValueError("No completed download with that ID belongs to this session")
            if self.workspace is None:
                raise ValueError("Configure a workspace destination before saving")
            target = self.workspace.resolve(destination, write=True)
            if not target.parent.is_dir():
                raise ValueError("Destination folder does not exist")
            source = self.directory / "artifacts" / artifact
            staged = target.parent / (".marvi-" + uuid4().hex + ".partial")
            try:
                shutil.copyfile(source, staged)
                # Link is atomic and fails if target exists; unlike replace it
                # cannot silently overwrite a file written since validation.
                os.link(staged, target)
            finally:
                staged.unlink(missing_ok=True)
            return {"path": str(target), "bytes": item["bytes"], "sha256": item["sha256"]}

        return self._loop.submit(save())

    def image(self, sid: str, revision: int, tab_id: str) -> bytes:
        async def capture():
            session = self._check(sid, revision)
            if session["state"] != "ready" or capture_barrier.blocked:
                raise ValueError("Browser is not available for observation")
            page = self._pages.get(sid, {}).get(tab_id)
            if page is None:
                raise ValueError("Select an exact tab ID")
            png = await page.screenshot(
                mask=[page.locator('input, textarea, [contenteditable="true"]')], timeout=5000
            )
            self._check(sid, revision)
            if capture_barrier.blocked:
                raise ValueError("Private input is active")
            return png

        return self._loop.submit(capture(), timeout=8)

    def control(self, sid: str, revision: int, command: str) -> dict:
        async def change():
            session = self._check(sid, revision)
            if command not in {"pause", "private", "resume", "stop", "close", "show"}:
                raise ValueError("Unknown browser command")
            if command == "show":
                pages = list(self._pages.get(sid, {}).values())
                if not pages:
                    raise ValueError("Browser is closed")
                await pages[0].bring_to_front()
                return self._public(session)
            if command == "resume":
                if sid not in self._contexts:
                    raise ValueError("Open this profile to restart its browser")
                if session["state"] not in {"private", "paused", "cancelled"}:
                    raise ValueError("Browser is not waiting for resume")
                if capture_barrier.blocked and not capture_barrier.owns(sid):
                    raise ValueError("Resume the browser with private input first")
                if sid in self._embedded:
                    await self._host_request("/private", {"id": sid, "active": False})
                capture_barrier.leave(sid)
                session["result"] = None
                self._change(session, "resuming", "Reading a fresh observation.")
                pages = self._pages.get(sid, {})
                tid = session.get("active_tab")
                if tid not in pages:
                    tid = next(iter(pages), None)
                self._operations[sid] = asyncio.create_task(self._act(sid, "read", {"tab_id": tid}))
                return self._public(session)
            if command == "private":
                if sid not in self._contexts:
                    raise ValueError("Wait for the browser to open before private input")
                capture_barrier.block(sid)
            self._change(session, "stopping", "Stopping automation; please wait before typing.")
            operation = self._operations.get(sid)
            if operation and not operation.done():
                # Playwright cancellation does not cancel a protocol command
                # already dispatched. Drain its bounded operation before ack.
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.shield(operation)
            session["result"] = None
            if command == "close":
                if sid in self._contexts:
                    await self._contexts[sid].close()
                else:
                    self._closed(sid)
            elif command == "private":
                for embedded_id in self._embedded:
                    await self._host_request("/private", {"id": embedded_id, "active": True})
                # A second session must not return a frame captured during
                # credential entry. Quiesce every browser observer first.
                for other_sid, other in list(self._operations.items()):
                    if other_sid != sid and not other.done():
                        self._change(
                            self.sessions[other_sid],
                            "stopping",
                            "Waiting for browser command before private input.",
                        )
                        with contextlib.suppress(asyncio.CancelledError):
                            await asyncio.shield(other)
                        self.sessions[other_sid]["result"] = None
                        self._change(
                            self.sessions[other_sid], "paused", "Private input in another browser."
                        )
                downloads = list(self._downloads)
                for download in downloads:
                    download.cancel()
                await asyncio.gather(*downloads, return_exceptions=True)
                # Bounded, and released if it does not come. `control` is
                # submitted with a 60s ceiling, so an unbounded wait here did
                # not hang for ever visibly -- it timed out the caller and left
                # the barrier closed behind it, which refuses every later
                # browser *and* computer action with nothing able to clear it.
                try:
                    await asyncio.to_thread(capture_barrier.enter, sid, PRIVATE_WAIT_SECONDS)
                except TimeoutError:
                    capture_barrier.leave(sid)
                    self._change(
                        session,
                        "paused",
                        "Private input did not start: something is still reading the page.",
                    )
                    raise ValueError(
                        "Private input did not start; a browser read is still running. Try again."
                    ) from None
                session["tabs"] = []
                self._change(
                    session,
                    "private",
                    "Private input — Marvi paused. Enter credentials in the website, then Resume.",
                )
            else:
                # Keep private capture protection until explicit Resume/Close.
                state = (
                    "private"
                    if capture_barrier.owns(sid)
                    else ("cancelled" if command == "stop" else "paused")
                )
                self._change(session, state, "Automation stopped. Resume explicitly to continue.")
            return self._public(session)

        return self._loop.submit(change(), timeout=60)

    def close(self):
        async def shutdown():
            for operation in self._operations.values():
                operation.cancel()
            await asyncio.gather(*self._operations.values(), return_exceptions=True)
            downloads = list(self._downloads)
            for download in downloads:
                download.cancel()
            await asyncio.gather(*downloads, return_exceptions=True)
            for context in list(self._contexts.values()):
                await context.close()
            if self._playwright:
                await self._playwright.stop()
            if self._network:
                await asyncio.to_thread(self._network.close)

        try:
            self._loop.submit(shutdown(), timeout=15)
        finally:
            for sid in self.sessions:
                capture_barrier.leave(sid)
            self._loop.stop()
            self._db.close()
