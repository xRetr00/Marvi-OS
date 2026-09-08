"""Real Chromium tests for the visible-browser backend (headless in CI)."""

import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.app import create_app
from marvi_gateway.browser_privacy import capture_barrier
from marvi_gateway.browser_workspace import BrowserWorkspace
from marvi_gateway.runtime import RuntimeStore
from marvi_gateway.tools import ToolRegistry


class Page(http.server.BaseHTTPRequestHandler):
    private_hits = 0

    def do_GET(self):
        if self.path == "/public-redirect":
            self.send_response(302)
            self.send_header("Location", "/private-redirect")
            self.end_headers()
            return
        if self.path == "/private-redirect":
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{self.server.server_port}/private-destination")
            self.end_headers()
            return
        if self.path == "/private-destination":
            Page.private_hits += 1
        if self.path == "/download":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", 'attachment; filename="invoice.txt"')
            self.end_headers()
            self.wfile.write(b"invoice fixture bytes")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"""<html><body><h1>Invoice fixture</h1>
          <label>Name<input aria-label="Name"></label>
          <label>Password<input type="password" aria-label="Password"></label>
          <button onclick="localStorage.setItem('signed-in', 'yes');document.querySelector('h1').textContent='Signed in'">Sign in</button>
          <button onclick="document.querySelector('h1').textContent=localStorage.getItem('signed-in')||'no'">Check session</button>
          <a href="/download">Download invoice</a>
          <a target="_blank" href="/second">Second tab</a></body></html>""")

    def log_message(self, *args):
        pass


@pytest.fixture
def browser(tmp_path):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    service = BrowserWorkspace(tmp_path / "browser", headless=True, allowed_origins=(origin,))
    yield service, origin
    service.close()
    server.shutdown()
    server.server_close()


def session(service, sid):
    return next(s for s in service.status()["sessions"] if s["id"] == sid)


def settled(service, sid):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        state = session(service, sid)
        if state["state"] not in {"starting", "running", "resuming", "stopping"}:
            return state
        time.sleep(0.03)
    pytest.fail("Browser operation did not settle")


def act(service, sid, action, arguments=None, action_id=""):
    state = session(service, sid)
    service.action(
        sid, state["revision"], action, arguments or {}, action_id or str(time.monotonic_ns())
    )
    return settled(service, sid)


def test_persistent_profile_actual_actions_and_isolation(browser):
    service, url = browser
    sid = service.start(url=url)["id"]
    assert settled(service, sid)["state"] == "ready"
    assert act(service, sid, "click", {"role": "button", "name": "Sign in"})["state"] == "ready"
    service.control(sid, session(service, sid)["revision"], "close")
    sid = service.start(url=url)["id"]
    settled(service, sid)
    result = act(service, sid, "click", {"role": "button", "name": "Check session"})
    assert "yes" in json.dumps(result["result"])
    with pytest.raises(ValueError, match="already has a browser"):
        service.start(url=url)
    profile = service.profile("create", "Work")["profiles"][-1]["id"]
    other = service.start(profile, url)["id"]
    settled(service, other)
    assert "no" in json.dumps(
        act(service, other, "click", {"role": "button", "name": "Check session"})["result"]
    )


@pytest.mark.parametrize("iteration", range(30))
def test_private_input_fresh_resume_and_stale_actions(browser, iteration):
    service, url = browser
    sid = service.start(url=url)["id"]
    state = settled(service, sid)
    private = service.control(sid, state["revision"], "private")
    assert private["state"] == "private"
    assert capture_barrier.blocked
    with pytest.raises(RuntimeError, match="Private"), capture_barrier.observe():
        pytest.fail("Capture must not start")
    with pytest.raises(ValueError):
        service.action(sid, private["revision"], "read", {}, "blocked")
    service.control(sid, private["revision"], "resume")
    resumed = settled(service, sid)
    assert resumed["state"] == "ready"
    assert not capture_barrier.blocked
    assert resumed["result"]
    with pytest.raises(ValueError, match="state changed"):
        service.action(sid, state["revision"], "read", {}, "stale")


def test_receipts_deduplicate_without_replaying(browser):
    service, url = browser
    sid = service.start(url=url)["id"]
    state = settled(service, sid)
    args = {"role": "button", "name": "Sign in"}
    receipt = service.action(sid, state["revision"], "click", args, "once")
    settled(service, sid)
    assert service.action(sid, state["revision"], "click", args, "once") == receipt
    with pytest.raises(ValueError, match="different arguments"):
        service.action(sid, state["revision"], "click", {}, "once")


def test_private_blocks_other_profiles_and_resume_with_multiple_tabs(browser):
    service, url = browser
    sid = service.start(url=url)["id"]
    settled(service, sid)
    act(service, sid, "new_tab", {"url": url + "/second"})
    state = session(service, sid)
    assert len(state["tabs"]) == 2
    private = service.control(sid, state["revision"], "private")
    profile = service.profile("create", "Separate")["profiles"][-1]["id"]
    with pytest.raises(ValueError, match="Private input"):
        service.start(profile, url)
    service.control(sid, private["revision"], "resume")
    assert settled(service, sid)["state"] == "ready"


@pytest.mark.parametrize("trigger", ["click", "navigate"])
def test_download_export_preserves_bytes_and_refuses_overwrite(browser, tmp_path, trigger):
    from marvi_gateway.workspace import Workspace

    service, url = browser
    service.workspace = Workspace(tmp_path)
    sid = service.start(url=url)["id"]
    settled(service, sid)
    if trigger == "click":
        act(service, sid, "click", {"role": "link", "name": "Download invoice"})
    else:
        act(service, sid, "navigate", {"url": url + "/download"})
    deadline = time.monotonic() + 5
    while "download" not in session(service, sid) and time.monotonic() < deadline:
        time.sleep(0.03)
    item = session(service, sid)["download"]
    service.export(sid, item["artifact"], "invoice.txt")
    assert (tmp_path / "invoice.txt").read_bytes() == b"invoice fixture bytes"
    with pytest.raises(FileExistsError):
        service.export(sid, item["artifact"], "invoice.txt")


def test_stop_cancels_pending_click_without_late_action(browser):
    service, url = browser
    sid = service.start(url=url)["id"]
    state = settled(service, sid)
    service.action(sid, state["revision"], "click", {"selector": "#absent"}, "pending")
    current = session(service, sid)
    stopped = service.control(sid, current["revision"], "stop")
    assert stopped["state"] == "cancelled"
    time.sleep(0.1)
    assert session(service, sid)["state"] == "cancelled"


def test_private_capture_barrier_waits_for_inflight_delivery():
    entered, release = threading.Event(), threading.Event()

    def observer():
        with capture_barrier.observe():
            entered.set()
            release.wait(3)

    thread = threading.Thread(target=observer)
    thread.start()
    assert entered.wait(2)
    acknowledged = threading.Event()

    def private():
        capture_barrier.enter("test")
        acknowledged.set()

    waiter = threading.Thread(target=private)
    waiter.start()
    assert not acknowledged.wait(0.05)
    release.set()
    assert acknowledged.wait(2)
    capture_barrier.leave("test")
    thread.join()
    waiter.join()


@pytest.mark.asyncio
async def test_gateway_confirmation_and_real_browser(browser, tmp_path):
    service, url = browser
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    app = create_app(tools=ToolRegistry(), runtime=runtime, browser_service=service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as client:
        started = await client.post("/browser/start", json={"url": url})
        sid = started.json()["id"]
        state = settled(service, sid)
        args = {
            "session_id": sid,
            "revision": state["revision"],
            "action": "click",
            "arguments": {"role": "button", "name": "Sign in"},
            "action_id": "approved",
            "request_confirmation": True,
        }
        proposed = await client.post("/tools/browser_action", json={"arguments": args})
        assert proposed.json()["status"] == "confirmation_required"
        approved = await client.post(
            f"/confirmations/{proposed.json()['token']}",
            json={"decision": "approve", "arguments": args},
        )
        assert approved.json()["status"] == "executed"
        assert "Signed in" in json.dumps(settled(service, sid)["result"])


@pytest.mark.asyncio
async def test_browser_api_requires_local_token_and_refuses_web_origin(browser, monkeypatch):
    service, _ = browser
    monkeypatch.setenv("MARVI_LOCAL_TOKEN", "fixture-token")
    app = create_app(tools=ToolRegistry(), browser_service=service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as client:
        assert (await client.get("/browser")).status_code == 403
        assert (
            await client.get("/browser", headers={"x-marvi-local": "fixture-token"})
        ).status_code == 200
        assert (
            await client.get(
                "/browser",
                headers={"x-marvi-local": "fixture-token", "sec-fetch-site": "cross-site"},
            )
        ).status_code == 403
        assert (await client.post("/tools/browser_open", json={"arguments": {}})).status_code == 403


def test_real_gateway_process_browser_handoff(browser, tmp_path):
    _, origin = browser
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    script = """
import sys
from pathlib import Path
import uvicorn
from marvi_gateway.app import create_app
from marvi_gateway.browser_workspace import BrowserWorkspace
from marvi_gateway.tools import ToolRegistry
service = BrowserWorkspace(Path(sys.argv[1]), headless=True, allowed_origins=(sys.argv[2],))
app = create_app(tools=ToolRegistry(), browser_service=service)
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=int(sys.argv[3]), log_level="error"))
@app.post("/_test_exit")
def stop():
    server.should_exit = True
    return {"stopping": True}
server.run()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path / "child-browser"), origin, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        env={
            **os.environ,
            "MARVI_HOME": str(tmp_path / "child-home"),
            "MARVI_LOCAL_TOKEN": "test-process",
        },
    )
    with httpx.Client(
        base_url=f"http://127.0.0.1:{port}", headers={"x-marvi-local": "test-process"}, timeout=10
    ) as client:
        try:
            deadline = time.monotonic() + 20
            while True:
                try:
                    if client.get("/browser").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline, "Gateway process did not become available"
                time.sleep(0.1)
            opened = client.post("/browser/start", json={"url": origin})
            assert opened.status_code == 200
            sid = opened.json()["id"]

            def state():
                return next(s for s in client.get("/browser").json()["sessions"] if s["id"] == sid)

            deadline = time.monotonic() + 20
            while state()["state"] == "starting":
                assert time.monotonic() < deadline
                time.sleep(0.1)
            private = client.post(
                f"/browser/{sid}/control",
                json={"revision": state()["revision"], "command": "private"},
            )
            assert private.json()["state"] == "private"
            assert client.get("/browser").json()["private_input"]
            closed = client.post(
                f"/browser/{sid}/control",
                json={"revision": state()["revision"], "command": "close"},
            )
            assert closed.json()["state"] == "closed"
            assert not client.get("/browser").json()["private_input"]
        finally:
            try:
                client.post("/_test_exit")
                process.wait(timeout=20)
            except (httpx.TransportError, subprocess.TimeoutExpired):
                process.terminate()
                process.wait(timeout=5)
    assert process.returncode == 0


def test_browser_image_uses_actual_tab_and_private_barrier(browser):
    from types import SimpleNamespace

    from marvi_gateway.browser_api import register_workspace_browser_tools

    service, url = browser
    sid = service.start(url=url)["id"]
    state = settled(service, sid)
    calls = []

    class Vision:
        def call_with_fallback(self, messages, **options):
            calls.append((messages, options))
            return SimpleNamespace(text="An invoice fixture is visible.")

    registry = ToolRegistry()
    register_workspace_browser_tools(registry, lambda: service, Vision())
    args = {
        "session_id": sid,
        "revision": state["revision"],
        "tab_id": state["tabs"][0]["id"],
        "question": "What is visible?",
    }
    spec = registry.get("browser_read_image")
    result = registry.execute(spec, args)
    assert "invoice fixture" in json.dumps(result)
    assert calls[0][1]["job"] == "vision"
    assert calls[0][0][1]["content"][1]["data"].startswith("iVBOR")
    service.control(sid, state["revision"], "private")
    with pytest.raises(RuntimeError, match="Private"):
        registry.execute(spec, args)
    assert len(calls) == 1


def test_legacy_mutation_requires_migration_instead_of_guessing_tab(browser):
    from marvi_gateway.browser_api import register_workspace_browser_tools

    service, _ = browser
    registry = ToolRegistry()
    register_workspace_browser_tools(registry, lambda: service)
    with pytest.raises(ValueError, match="not executed"):
        registry.execute(registry.get("browser_click"), {"selector": "button"})


@pytest.mark.parametrize("path", ["/private-redirect", "/public-redirect"])
def test_redirect_cannot_reach_private_destination(browser, path):
    service, url = browser
    Page.private_hits = 0
    sid = service.start(url=url)["id"]
    settled(service, sid)
    act(service, sid, "navigate", {"url": url + path})
    assert Page.private_hits == 0

def test_embedded_connection_failure_releases_host_profile(browser, monkeypatch):
    service, origin = browser
    # Real proxy and Playwright process; only the host control endpoint is a
    # fixture. Refusing CDP must still release the host's acquired profile.
    service.headless = False
    service.register_host('http://127.0.0.1:1', 'a' * 64)
    calls = []

    async def host_request(path, body):
        calls.append((path, body['id']))
        return {'endpoint': 'ws://127.0.0.1:1/refused', 'downloads': str(service.directory)}

    monkeypatch.setattr(service, '_host_request', host_request)
    sid = service.start(url=origin)['id']
    state = settled(service, sid)
    assert state['state'] == 'failed'
    assert state['error_stage'] == 'connect_embedded_protocol'
    assert calls == [('/open', sid), ('/close', sid)]


def test_new_tab_without_url_opens_blank(browser):
    service, origin = browser
    sid = service.start(url=origin)['id']
    state = settled(service, sid)
    service.action(sid, state['revision'], 'new_tab', {}, 'blank-tab')
    state = settled(service, sid)
    assert state['state'] == 'ready'
    assert len(state['tabs']) == 2
    assert any(tab['url'] == 'about:blank' for tab in state['tabs'])

@pytest.mark.asyncio
async def test_browser_status_timeout_is_explicit():
    from fastapi import FastAPI

    from marvi_gateway.browser_api import browser_router

    class Busy:
        def status(self):
            raise TimeoutError()

    app = FastAPI()
    app.include_router(browser_router(lambda: Busy(), lambda *_: None))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://localhost') as client:
        response = await client.get('/browser')
    assert response.status_code == 503
    assert 'busy' in response.json()['detail']
